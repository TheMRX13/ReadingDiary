package main

import (
	"context"
	"embed"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"
	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

//go:embed web/*
var webFiles embed.FS

// Database Models
type Book struct {
	ID              uint      `json:"id" gorm:"primaryKey"`
	Title           string    `json:"title" gorm:"not null"`
	Author          string    `json:"author" gorm:"not null"`
	Genre           string    `json:"genre"`
	Pages           int       `json:"pages"`
	Format          string    `json:"format"`
	Publisher       string    `json:"publisher"`
	Status          string    `json:"status" gorm:"default:'Ungelesen'"`
	PublishDate     string    `json:"publish_date"`
	Series          string    `json:"series"`
	Volume          int       `json:"volume"`
	CoverImage      string    `json:"cover_image"`
	ReadingProgress int       `json:"reading_progress" gorm:"default:0"`
	Rating          int       `json:"rating" gorm:"default:0"`
	Spice           int       `json:"spice" gorm:"default:0"`
	Tension         int       `json:"tension" gorm:"default:0"`
	Fiction         bool      `json:"fiction" gorm:"default:true"`
	Review          string    `json:"review"`
	CreatedAt       time.Time `json:"created_at"`
	UpdatedAt       time.Time `json:"updated_at"`
}

type Wishlist struct {
	ID          uint      `json:"id" gorm:"primaryKey"`
	Title       string    `json:"title" gorm:"not null"`
	Author      string    `json:"author" gorm:"not null"`
	Genre       string    `json:"genre"`
	Pages       int       `json:"pages"`
	Publisher   string    `json:"publisher"`
	PublishDate string    `json:"publish_date"`
	Series      string    `json:"series"`
	Volume      int       `json:"volume"`
	CoverImage  string    `json:"cover_image"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}

type Quote struct {
	ID        uint      `json:"id" gorm:"primaryKey"`
	Quote     string    `json:"quote" gorm:"not null"`
	Book      string    `json:"book" gorm:"not null"`
	Page      int       `json:"page"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type Genre struct {
	ID        uint      `json:"id" gorm:"primaryKey"`
	Name      string    `json:"name" gorm:"unique;not null"`
	CreatedAt time.Time `json:"created_at"`
}

type Publisher struct {
	ID        uint      `json:"id" gorm:"primaryKey"`
	Name      string    `json:"name" gorm:"unique;not null"`
	CreatedAt time.Time `json:"created_at"`
}

type ReadingGoal struct {
	ID        uint      `json:"id" gorm:"primaryKey"`
	Enabled   bool      `json:"enabled" gorm:"default:false"`
	Type      string    `json:"type" gorm:"default:'year'"` // week, month, year
	Target    int       `json:"target" gorm:"default:0"`
	Current   int       `json:"current" gorm:"default:0"`
	UpdatedAt time.Time `json:"updated_at"`
}

type ProgressHistory struct {
	ID        uint      `json:"id" gorm:"primaryKey"`
	BookID    uint      `json:"book_id" gorm:"not null"`
	Page      int       `json:"page" gorm:"not null"`
	Change    int       `json:"change" gorm:"not null"`
	Date      time.Time `json:"date" gorm:"not null"`
	CreatedAt time.Time `json:"created_at"`
}

// Global variables
var (
	db             *gorm.DB
	serverPort     = 7443
	serverPassword = "admin123"
	serverRunning  = false
	httpServer     *http.Server
	ipAddresses    []string
	guiInstance    *ServerGUI // Globale Referenz für Logging
)

// Custom Logger Interface
type Logger interface {
	Log(level string, message string)
	Info(message string)
	Warning(message string)
	Error(message string)
	Debug(message string)
}

// Combined Logger (Console + GUI)
type CombinedLogger struct {
	gui *ServerGUI
}

func NewCombinedLogger(gui *ServerGUI) *CombinedLogger {
	return &CombinedLogger{gui: gui}
}

func (l *CombinedLogger) Log(level string, message string) {
	// GUI Logging (falls verfügbar)
	if l != nil && l.gui != nil {
		l.gui.addLogWithLevel(level, message)
	} else {
		// Fallback zu Konsole wenn GUI nicht verfügbar
		timestamp := time.Now().Format("15:04:05")
		logMsg := fmt.Sprintf("[%s] [%s] %s", timestamp, level, message)
		fmt.Println(logMsg)
	}

	// Zusätzlich bei kritischen Fehlern auch in Konsole
	if level == "ERROR" {
		timestamp := time.Now().Format("15:04:05")
		logMsg := fmt.Sprintf("[%s] [%s] %s", timestamp, level, message)
		fmt.Println(logMsg)
	}
}

func (l *CombinedLogger) Info(message string) {
	l.Log("INFO", message)
}

func (l *CombinedLogger) Warning(message string) {
	l.Log("WARN", message)
}

func (l *CombinedLogger) Error(message string) {
	l.Log("ERROR", message)
}

func (l *CombinedLogger) Debug(message string) {
	l.Log("DEBUG", message)
}

var logger *CombinedLogger

// Custom Gin Logger Middleware
func GinLoggerMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()

		// Request Info
		if logger != nil {
			logger.Info(fmt.Sprintf("→ %s %s from %s", c.Request.Method, c.Request.URL.Path, c.ClientIP()))
		}

		c.Next()

		// Response Info
		if logger != nil {
			duration := time.Since(start)
			status := c.Writer.Status()
			size := c.Writer.Size()

			statusLevel := "INFO"
			if status >= 400 && status < 500 {
				statusLevel = "WARN"
			} else if status >= 500 {
				statusLevel = "ERROR"
			}

			logger.Log(statusLevel, fmt.Sprintf("← %d %s (%v) %d bytes",
				status, c.Request.URL.Path, duration, size))
		}
	}
}

// GUI Components
type ServerGUI struct {
	app           fyne.App
	window        fyne.Window
	statusLabel   *widget.Label
	portEntry     *widget.Entry
	passwordEntry *widget.Entry
	startButton   *widget.Button
	logText       *widget.Label
	ipList        *widget.List
	uptimeLabel   *widget.Label
	startTime     time.Time
}

func main() {
	// Wenn Command-Line Argumente vorhanden, nur Server starten
	if len(os.Args) > 1 {
		if len(os.Args) >= 2 {
			if port, err := strconv.Atoi(os.Args[1]); err == nil {
				serverPort = port
			}
		}
		if len(os.Args) >= 3 {
			serverPassword = os.Args[2]
		}

		// Nur Server starten (für Tests)
		startServerOnly()
		return
	}

	// GUI starten
	gui := &ServerGUI{}
	gui.setupGUI()
	gui.window.ShowAndRun()
}

func (g *ServerGUI) setupGUI() {
	g.app = app.New()
	g.app.SetIcon(nil) // Hier könnte ein Icon gesetzt werden

	// Setze Light Theme für bessere Lesbarkeit
	g.app.Settings().SetTheme(theme.LightTheme())

	g.window = g.app.NewWindow("Reading Diary Server")
	g.window.Resize(fyne.NewSize(800, 600))
	g.window.CenterOnScreen()

	// Status
	g.statusLabel = widget.NewLabel("Server gestoppt")
	g.uptimeLabel = widget.NewLabel("Laufzeit: 00:00:00")

	// Einstellungen
	g.portEntry = widget.NewEntry()
	g.portEntry.SetText(strconv.Itoa(serverPort))
	g.portEntry.Validator = func(s string) error {
		if port, err := strconv.Atoi(s); err != nil || port < 1 || port > 65535 {
			return fmt.Errorf("ungültiger Port")
		}
		return nil
	}

	g.passwordEntry = widget.NewPasswordEntry()
	g.passwordEntry.SetText(serverPassword)

	// Buttons
	g.startButton = widget.NewButton("Server Starten", g.toggleServer)
	openWebButton := widget.NewButton("Web-Interface öffnen", g.openWebInterface)
	refreshIPButton := widget.NewButton("IP-Adressen aktualisieren", g.refreshIPAddresses)

	// Log - ZUERST initialisieren
	g.logText = widget.NewLabel("🔵 [INFO] Server GUI gestartet - Reading Diary v1.0 by TheMRX\n")
	g.logText.Wrapping = fyne.TextWrapWord
	g.logText.Alignment = fyne.TextAlignLeading
	g.logText.TextStyle = fyne.TextStyle{Monospace: true}

	// JETZT ERST Logger initialisieren, nachdem logText bereit ist
	guiInstance = g
	logger = NewCombinedLogger(g)

	logger.Info("GUI-System initialisiert")
	logger.Info("Reading Diary Server v1.0 - Coded by TheMRX")

	// IP-Adressen Liste
	g.ipList = widget.NewList(
		func() int { return len(ipAddresses) },
		func() fyne.CanvasObject { return widget.NewLabel("") },
		func(id int, o fyne.CanvasObject) {
			if id < len(ipAddresses) {
				o.(*widget.Label).SetText(ipAddresses[id])
			}
		},
	)

	// Layout
	settingsForm := container.NewVBox(
		widget.NewLabel("Server Einstellungen"),
		widget.NewFormItem("Port:", g.portEntry).Widget,
		widget.NewFormItem("Passwort:", g.passwordEntry).Widget,
		g.startButton,
	)

	statusContainer := container.NewVBox(
		widget.NewLabel("Server Status"),
		g.statusLabel,
		g.uptimeLabel,
		openWebButton,
	)

	ipContainer := container.NewVBox(
		widget.NewLabel("Verfügbare URLs"),
		refreshIPButton,
		g.ipList,
	)

	topContainer := container.NewHBox(settingsForm, statusContainer, ipContainer)

	logContainer := container.NewBorder(
		container.NewHBox(
			widget.NewLabel("Server Log & Aktivitäten"),
			widget.NewSeparator(),
			widget.NewButton("Log löschen", func() {
				g.logText.SetText("🔵 [INFO] Log geleert\n")
			}),
		),
		nil, nil, nil,
		container.NewScroll(g.logText),
	)

	creditsLabel := widget.NewRichTextFromMarkdown("**Reading Diary Server v1.0**\n\nCoded by TheMRX - Pascal Keller")
	creditsLabel.Wrapping = fyne.TextWrapWord

	mainContainer := container.NewBorder(
		container.NewVBox(
			widget.NewCard("", "", topContainer),
			widget.NewSeparator(),
		),
		container.NewVBox(
			widget.NewSeparator(),
			creditsLabel,
		),
		nil, nil,
		widget.NewCard("", "", logContainer),
	)

	g.window.SetContent(mainContainer)

	// Initial IP refresh
	g.refreshIPAddresses()

	// Uptime Timer
	go g.updateUptime()

	// Window close handler
	g.window.SetCloseIntercept(func() {
		if serverRunning {
			dialog.ShowConfirm("Server läuft",
				"Der Server läuft noch. Möchten Sie ihn stoppen und beenden?",
				func(yes bool) {
					if yes {
						g.stopServer()
						g.window.Close()
					}
				}, g.window)
		} else {
			g.window.Close()
		}
	})
}

func (g *ServerGUI) toggleServer() {
	if serverRunning {
		g.stopServer()
	} else {
		g.startServer()
	}
}

func (g *ServerGUI) startServer() {
	logger.Info("Server-Start angefordert...")

	// Validierung
	if err := g.portEntry.Validator(g.portEntry.Text); err != nil {
		logger.Error(fmt.Sprintf("Port-Validierung fehlgeschlagen: %v", err))
		dialog.ShowError(err, g.window)
		return
	}

	port, _ := strconv.Atoi(g.portEntry.Text)
	password := g.passwordEntry.Text

	serverPort = port
	serverPassword = password

	logger.Info(fmt.Sprintf("Server-Konfiguration: Port=%d, Passwort-Länge=%d Zeichen", port, len(password)))

	// Datenbank initialisieren
	logger.Info("Initialisiere Datenbank...")
	if err := initDatabase(); err != nil {
		logger.Error(fmt.Sprintf("Datenbank-Initialisierung fehlgeschlagen: %v", err))
		g.addLog(fmt.Sprintf("Fehler bei Datenbank: %v", err))
		dialog.ShowError(fmt.Errorf("datenbankfehler: %v", err), g.window)
		return
	}
	logger.Info("Datenbank erfolgreich initialisiert")

	// Server starten
	logger.Info("Konfiguriere Gin-Router...")
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Recovery())

	// Custom Logger Middleware verwenden
	router.Use(GinLoggerMiddleware())
	logger.Info("Custom Logger Middleware aktiviert")

	// CORS
	router.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"*"},
		ExposeHeaders:    []string{"*"},
		AllowCredentials: true,
	}))
	logger.Info("CORS-Middleware konfiguriert")

	setupRoutes(router)
	logger.Info("API-Routen registriert")

	httpServer = &http.Server{
		Addr:    fmt.Sprintf(":%d", serverPort),
		Handler: router,
	}

	go func() {
		logger.Info(fmt.Sprintf("Starte HTTP-Server auf Port %d...", serverPort))
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error(fmt.Sprintf("HTTP-Server Fehler: %v", err))
		}
	}()

	serverRunning = true
	g.startTime = time.Now()
	g.statusLabel.SetText(fmt.Sprintf("Server läuft auf Port %d", serverPort))
	g.startButton.SetText("Server Stoppen")
	g.portEntry.Disable()
	g.passwordEntry.Disable()

	g.addLog("Server erfolgreich gestartet!")
	g.addLog(fmt.Sprintf("Passwort: %s", serverPassword))
	g.addLog(fmt.Sprintf("Web-Interface: http://localhost:%d", serverPort))
	logger.Info("🚀 Server erfolgreich gestartet!")
	logger.Info(fmt.Sprintf("🔑 Login-Passwort: %s", serverPassword))
	logger.Info(fmt.Sprintf("🌐 Web-Interface verfügbar: http://localhost:%d", serverPort))

	g.refreshIPAddresses()
	logger.Info("IP-Adressen aktualisiert - Server bereit für Verbindungen")
}

func (g *ServerGUI) stopServer() {
	logger.Info("Server-Stopp angefordert...")

	if httpServer != nil {
		logger.Info("Beende HTTP-Server...")
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		if err := httpServer.Shutdown(ctx); err != nil {
			logger.Error(fmt.Sprintf("Fehler beim Stoppen des HTTP-Servers: %v", err))
			g.addLog(fmt.Sprintf("Fehler beim Stoppen: %v", err))
		} else {
			logger.Info("HTTP-Server erfolgreich gestoppt")
		}
	}

	serverRunning = false
	g.statusLabel.SetText("Server gestoppt")
	g.startButton.SetText("Server Starten")
	g.portEntry.Enable()
	g.passwordEntry.Enable()
	g.uptimeLabel.SetText("Laufzeit: 00:00:00")

	g.addLog("Server gestoppt")
	logger.Info("🛑 Server vollständig gestoppt - Bereit für Neustart")
}

func (g *ServerGUI) openWebInterface() {
	if !serverRunning {
		logger.Warning("Versuch Web-Interface zu öffnen, aber Server läuft nicht")
		dialog.ShowInformation("Fehler", "Server muss zuerst gestartet werden!", g.window)
		return
	}

	url := fmt.Sprintf("http://localhost:%d", serverPort)
	logger.Info(fmt.Sprintf("Öffne Web-Interface: %s", url))

	var cmd *exec.Cmd

	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	case "darwin":
		cmd = exec.Command("open", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}

	if err := cmd.Start(); err != nil {
		logger.Error(fmt.Sprintf("Fehler beim Öffnen des Browsers: %v", err))
		g.addLog(fmt.Sprintf("Fehler beim Öffnen des Browsers: %v", err))
	} else {
		logger.Info("🌐 Web-Interface erfolgreich im Browser geöffnet")
		g.addLog("Web-Interface geöffnet")
	}
}

func (g *ServerGUI) refreshIPAddresses() {
	logger.Debug("Aktualisiere verfügbare IP-Adressen...")
	ipAddresses = []string{}
	ipAddresses = append(ipAddresses, fmt.Sprintf("http://localhost:%d", serverPort))

	interfaces, err := net.Interfaces()
	if err != nil {
		logger.Warning(fmt.Sprintf("Fehler beim Ermitteln der Netzwerk-Interfaces: %v", err))
		g.addLog(fmt.Sprintf("Fehler beim Ermitteln der Netzwerk-Interfaces: %v", err))
		return
	}

	interfaceCount := 0
	for _, iface := range interfaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}

		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}

		for _, addr := range addrs {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			}

			if ip == nil || ip.IsLoopback() {
				continue
			}

			if ip.To4() != nil {
				url := fmt.Sprintf("http://%s:%d", ip.String(), serverPort)
				ipAddresses = append(ipAddresses, url)
				logger.Debug(fmt.Sprintf("Gefundene IP-Adresse: %s", url))
				interfaceCount++
			}
		}
	}

	g.ipList.Refresh()
	g.addLog("IP-Adressen aktualisiert")
	logger.Info(fmt.Sprintf("IP-Adressen aktualisiert - %d Netzwerk-Interfaces gefunden", interfaceCount))
}

func (g *ServerGUI) addLog(message string) {
	timestamp := time.Now().Format("15:04:05")
	logEntry := fmt.Sprintf("[%s] %s\n", timestamp, message)
	g.logText.SetText(g.logText.Text + logEntry)
}

func (g *ServerGUI) addLogWithLevel(level string, message string) {
	// Sicherheitscheck
	if g == nil || g.logText == nil {
		// Fallback zu Konsole wenn GUI nicht bereit ist
		timestamp := time.Now().Format("15:04:05")
		fmt.Printf("[%s] [%s] %s\n", timestamp, level, message)
		return
	}

	timestamp := time.Now().Format("15:04:05")
	levelColor := ""
	switch level {
	case "ERROR":
		levelColor = "🔴"
	case "WARN":
		levelColor = "🟡"
	case "INFO":
		levelColor = "🔵"
	case "DEBUG":
		levelColor = "⚪"
	default:
		levelColor = "⚪"
	}

	logEntry := fmt.Sprintf("[%s] %s [%s] %s\n", timestamp, levelColor, level, message)
	currentText := g.logText.Text
	newText := currentText + logEntry

	// Begrenze die Log-Größe (letzte 1000 Zeilen behalten)
	lines := strings.Split(newText, "\n")
	if len(lines) > 1000 {
		lines = lines[len(lines)-1000:]
		newText = strings.Join(lines, "\n")
	}

	g.logText.SetText(newText)
}

func (g *ServerGUI) updateUptime() {
	for {
		time.Sleep(1 * time.Second)
		if serverRunning {
			uptime := time.Since(g.startTime)
			hours := int(uptime.Hours())
			minutes := int(uptime.Minutes()) % 60
			seconds := int(uptime.Seconds()) % 60
			g.uptimeLabel.SetText(fmt.Sprintf("Laufzeit: %02d:%02d:%02d", hours, minutes, seconds))
		}
	}
}

// Server-only mode (für Command-Line oder GUI-Anwendung)
func startServerOnly() {
	// Erstelle minimale GUI für Server-Only-Modus
	serverApp := app.New()
	// Setze Light Theme für bessere Lesbarkeit
	serverApp.Settings().SetTheme(theme.LightTheme())

	serverWindow := serverApp.NewWindow("Reading Diary Server")
	serverWindow.Resize(fyne.NewSize(500, 300))
	serverWindow.CenterOnScreen()

	statusLabel := widget.NewLabel("Starting Reading Diary Server...")
	logText := widget.NewEntry()
	logText.MultiLine = true
	logText.Wrapping = fyne.TextWrapWord
	logText.Disable()

	logText.SetText(fmt.Sprintf("Starting Reading Diary Server on port %d...\n", serverPort))

	// Datenbank initialisieren
	if err := initDatabase(); err != nil {
		logText.SetText(logText.Text + fmt.Sprintf("Database error: %v\n", err))
		statusLabel.SetText("Database Error - Check logs")
		content := container.NewVBox(
			statusLabel,
			widget.NewSeparator(),
			container.NewScroll(logText),
		)
		serverWindow.SetContent(content)
		serverWindow.ShowAndRun()
		return
	}

	logText.SetText(logText.Text + "Database initialized successfully\n")

	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Logger(), gin.Recovery())

	router.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"*"},
		ExposeHeaders:    []string{"*"},
		AllowCredentials: true,
	}))

	setupRoutes(router)

	logText.SetText(logText.Text + fmt.Sprintf("Server running on http://localhost:%d\n", serverPort))
	logText.SetText(logText.Text + fmt.Sprintf("Password: %s\n", serverPassword))
	statusLabel.SetText("Server Running")

	content := container.NewVBox(
		statusLabel,
		widget.NewSeparator(),
		container.NewScroll(logText),
	)
	serverWindow.SetContent(content)

	// Server in Goroutine starten
	go func() {
		if err := router.Run(fmt.Sprintf(":%d", serverPort)); err != nil {
			logText.SetText(logText.Text + fmt.Sprintf("Server error: %v\n", err))
			statusLabel.SetText("Server Error")
		}
	}()

	serverWindow.ShowAndRun()
}

func initDatabase() error {
	if logger != nil {
		logger.Info("Verbinde mit SQLite-Datenbank...")
	}

	var err error
	db, err = gorm.Open(sqlite.Open("reading_diary.db"), &gorm.Config{})
	if err != nil {
		if logger != nil {
			logger.Error(fmt.Sprintf("Datenbankverbindung fehlgeschlagen: %v", err))
		}
		return err
	}

	if logger != nil {
		logger.Info("Führe Datenbank-Migration durch...")
	}

	// Auto-migrate
	if err := db.AutoMigrate(&Book{}, &Wishlist{}, &Quote{}, &Genre{}, &Publisher{}, &ReadingGoal{}, &ProgressHistory{}); err != nil {
		if logger != nil {
			logger.Error(fmt.Sprintf("Datenbank-Migration fehlgeschlagen: %v", err))
		}
		return err
	}

	if logger != nil {
		logger.Info("✅ Datenbank erfolgreich initialisiert und migriert")
	}

	return nil
}

func setupRoutes(router *gin.Engine) {
	// Static files from embedded filesystem
	router.GET("/static/*filepath", func(c *gin.Context) {
		path := c.Param("filepath")
		if path == "/style.css" {
			data, err := webFiles.ReadFile("web/style.css")
			if err != nil {
				c.String(404, "Not found")
				return
			}
			c.Data(200, "text/css", data)
			return
		}
		if path == "/app.js" {
			data, err := webFiles.ReadFile("web/app.js")
			if err != nil {
				c.String(404, "Not found")
				return
			}
			c.Data(200, "application/javascript", data)
			return
		}
		if path == "/manifest.json" {
			data, err := webFiles.ReadFile("web/manifest.json")
			if err != nil {
				c.String(404, "Not found")
				return
			}
			c.Data(200, "application/json", data)
			return
		}
		if path == "/sw.js" {
			data, err := webFiles.ReadFile("web/sw.js")
			if err != nil {
				c.String(404, "Not found")
				return
			}
			c.Data(200, "application/javascript", data)
			return
		}
		// Handle icon files
		if strings.HasPrefix(path, "/icons/") {
			iconPath := "web" + path
			data, err := webFiles.ReadFile(iconPath)
			if err != nil {
				c.String(404, "Not found")
				return
			}
			c.Data(200, "image/png", data)
			return
		}
		c.String(404, "Not found")
	})

	// Cover images serving
	router.Static("/uploads", "./uploads")

	router.GET("/", func(c *gin.Context) {
		data, err := webFiles.ReadFile("web/index.html")
		if err != nil {
			c.String(404, "Not found")
			return
		}
		c.Data(200, "text/html; charset=utf-8", data)
	})

	// API routes
	api := router.Group("/api")
	{
		api.POST("/login", login)

		// Protected routes
		protected := api.Group("/", authMiddleware())
		{
			protected.GET("/books", getBooks)
			protected.POST("/books", createBook)
			protected.GET("/books/:id", getBook)
			protected.PUT("/books/:id", updateBook)
			protected.DELETE("/books/:id", deleteBook)
			protected.POST("/books/:id/cover", uploadBookCover)
			protected.GET("/books/:id/progress-history", getProgressHistory)
			protected.PUT("/books/:id/status", updateBookStatus)

			protected.GET("/wishlist", getWishlist)
			protected.GET("/wishlist/:id", getWishlistItem)
			protected.POST("/wishlist", createWishlistItem)
			protected.PUT("/wishlist/:id", updateWishlistItem)
			protected.DELETE("/wishlist/:id", deleteWishlistItem)
			protected.POST("/wishlist/:id/buy", buyWishlistItem)
			protected.POST("/wishlist/:id/cover", uploadWishlistCover)
			protected.POST("/wishlist/:id/move-cover/:book_id", moveCoverFromWishlistToBook)

			protected.GET("/quotes", getQuotes)
			protected.POST("/quotes", createQuote)
			protected.DELETE("/quotes/:id", deleteQuote)

			protected.GET("/stats", getStats)
			protected.GET("/stats/genres", getGenreStats)
			protected.GET("/stats/publishers", getPublisherStats)

			protected.GET("/genres", getGenres)
			protected.POST("/genres", createGenre)
			protected.DELETE("/genres/:id", deleteGenre)

			protected.GET("/publishers", getPublishers)
			protected.POST("/publishers", createPublisher)
			protected.DELETE("/publishers/:id", deletePublisher)

			protected.GET("/reading-goal", getReadingGoal)
			protected.PUT("/reading-goal", updateReadingGoal)
		}
	}
}

// Auth middleware
func authMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		auth := c.GetHeader("Authorization")
		if auth == "" {
			c.JSON(401, gin.H{"error": "Keine Autorisierung"})
			c.Abort()
			return
		}

		token := strings.TrimPrefix(auth, "Bearer ")
		if token != serverPassword {
			c.JSON(401, gin.H{"error": "Ungültige Autorisierung"})
			c.Abort()
			return
		}

		c.Next()
	}
}

// API Handlers
func login(c *gin.Context) {
	var req struct {
		Password string `json:"password"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		logger.Warning(fmt.Sprintf("Login-Versuch mit ungültiger Anfrage von %s", c.ClientIP()))
		c.JSON(400, gin.H{"error": "Ungültige Anfrage"})
		return
	}

	if req.Password != serverPassword {
		logger.Warning(fmt.Sprintf("Fehlerhafter Login-Versuch von %s", c.ClientIP()))
		c.JSON(401, gin.H{"error": "Ungültiges Passwort"})
		return
	}

	logger.Info(fmt.Sprintf("Erfolgreiche Anmeldung von %s", c.ClientIP()))
	c.JSON(200, gin.H{
		"token":   serverPassword,
		"message": "Erfolgreich angemeldet",
	})
}

func getBooks(c *gin.Context) {
	var books []Book
	query := db

	// Search
	if search := c.Query("search"); search != "" {
		query = query.Where("title LIKE ? OR author LIKE ?", "%"+search+"%", "%"+search+"%")
	}

	if err := query.Find(&books).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	c.JSON(200, books)
}

func createBook(c *gin.Context) {
	var book Book
	if err := c.ShouldBindJSON(&book); err != nil {
		logger.Error(fmt.Sprintf("createBook: Ungültige JSON-Daten: %v", err))
		c.JSON(400, gin.H{"error": fmt.Sprintf("Ungültige JSON-Daten: %v", err)})
		return
	}

	// Debug: Alle eingehenden Daten loggen
	logger.Debug(fmt.Sprintf("createBook: Empfangene Daten: %+v", book))

	// Validierung der Pflichtfelder
	if book.Title == "" {
		logger.Warning("createBook: Titel fehlt")
		c.JSON(400, gin.H{"error": "Titel ist erforderlich"})
		return
	}
	if book.Author == "" {
		logger.Warning("createBook: Autor fehlt")
		c.JSON(400, gin.H{"error": "Autor ist erforderlich"})
		return
	}
	if book.Genre == "" {
		logger.Warning("createBook: Genre fehlt")
		c.JSON(400, gin.H{"error": "Genre ist erforderlich"})
		return
	}
	if book.Pages <= 0 {
		c.JSON(400, gin.H{"error": "Seitenzahl muss größer als 0 sein"})
		return
	}
	if book.Format == "" {
		c.JSON(400, gin.H{"error": "Format ist erforderlich"})
		return
	}
	if book.Publisher == "" {
		logger.Warning("createBook: Verlag fehlt")
		c.JSON(400, gin.H{"error": "Verlag ist erforderlich"})
		return
	}

	// Automatisches Erstellen des Verlags falls er nicht existiert
	if err := ensurePublisherExists(book.Publisher); err != nil {
		logger.Error(fmt.Sprintf("createBook: Fehler beim Erstellen des Verlags: %v", err))
		c.JSON(500, gin.H{"error": fmt.Sprintf("Fehler beim Verarbeiten des Verlags: %v", err)})
		return
	}
	if book.PublishDate == "" {
		logger.Warning(fmt.Sprintf("createBook: Erscheinungsdatum fehlt: '%s'", book.PublishDate))
		c.JSON(400, gin.H{"error": "Erscheinungsdatum ist erforderlich"})
		return
	}

	logger.Debug("createBook: Alle Validierungen bestanden, erstelle Buch")

	if err := db.Create(&book).Error; err != nil {
		logger.Error(fmt.Sprintf("createBook: Datenbankfehler: %v", err))
		c.JSON(500, gin.H{"error": fmt.Sprintf("Konnte Buch nicht erstellen: %v", err)})
		return
	}

	logger.Info(fmt.Sprintf("createBook: Neues Buch erstellt - ID: %d, Titel: %s", book.ID, book.Title))
	c.JSON(201, book)
}

func getBook(c *gin.Context) {
	id := c.Param("id")
	var book Book

	if err := db.First(&book, id).Error; err != nil {
		c.JSON(404, gin.H{"error": "Buch nicht gefunden"})
		return
	}

	c.JSON(200, book)
}

func updateBook(c *gin.Context) {
	id := c.Param("id")
	var existingBook Book

	if err := db.First(&existingBook, id).Error; err != nil {
		c.JSON(404, gin.H{"error": "Buch nicht gefunden"})
		return
	}

	// Debug: Zeige empfangene Daten
	var requestData map[string]interface{}
	if err := c.ShouldBindJSON(&requestData); err != nil {
		logger.Error(fmt.Sprintf("updateBook: Fehler beim Parsen der JSON-Daten: %v", err))
		c.JSON(400, gin.H{"error": "Ungültige Daten"})
		return
	}
	logger.Debug(fmt.Sprintf("updateBook: Empfangene Daten: %+v", requestData))

	// Erstelle ein neues Book-Objekt basierend auf dem bestehenden Buch
	var updatedBook Book
	updatedBook = existingBook // Kopiere alle bestehenden Werte

	// Manuell die Felder aktualisieren, die im Request enthalten sind
	if title, ok := requestData["title"].(string); ok {
		updatedBook.Title = title
	}
	if author, ok := requestData["author"].(string); ok {
		updatedBook.Author = author
	}
	if genre, ok := requestData["genre"].(string); ok {
		updatedBook.Genre = genre
	}
	if publisher, ok := requestData["publisher"].(string); ok {
		updatedBook.Publisher = publisher
		// Automatisches Erstellen des Verlags falls er nicht existiert
		if publisher != "" {
			if err := ensurePublisherExists(publisher); err != nil {
				logger.Error(fmt.Sprintf("updateBook: Fehler beim Erstellen des Verlags: %v", err))
				c.JSON(500, gin.H{"error": fmt.Sprintf("Fehler beim Verarbeiten des Verlags: %v", err)})
				return
			}
		}
	}
	if publishDate, ok := requestData["publish_date"].(string); ok {
		updatedBook.PublishDate = publishDate
	}
	if series, ok := requestData["series"].(string); ok {
		updatedBook.Series = series
	}
	if review, ok := requestData["review"].(string); ok {
		updatedBook.Review = review
	}
	if format, ok := requestData["format"].(string); ok {
		updatedBook.Format = format
	}
	if coverImage, ok := requestData["cover_image"].(string); ok {
		updatedBook.CoverImage = coverImage
	}

	// Speichere den alten Lesefortschritt für Progress-History
	oldProgress := existingBook.ReadingProgress

	// Numerische Felder - beide Varianten prüfen
	if pages, ok := requestData["pages"].(float64); ok {
		updatedBook.Pages = int(pages)
	}
	if volume, ok := requestData["volume"].(float64); ok {
		updatedBook.Volume = int(volume)
	}
	if rating, ok := requestData["rating"].(float64); ok {
		updatedBook.Rating = int(rating)
	}
	if spice, ok := requestData["spice"].(float64); ok {
		updatedBook.Spice = int(spice)
	}
	if tension, ok := requestData["tension"].(float64); ok {
		updatedBook.Tension = int(tension)
	}
	if readingProgress, ok := requestData["reading_progress"].(float64); ok {
		updatedBook.ReadingProgress = int(readingProgress)
	} else if readingProgress, ok := requestData["readingProgress"].(float64); ok {
		updatedBook.ReadingProgress = int(readingProgress)
	}

	// Status Feld - sowohl status als auch is_read für Rückwärtskompatibilität
	if status, ok := requestData["status"].(string); ok {
		updatedBook.Status = status
	} else if isRead, ok := requestData["is_read"].(bool); ok {
		if isRead {
			updatedBook.Status = "Gelesen"
		} else {
			updatedBook.Status = "Ungelesen"
		}
	} else if isRead, ok := requestData["isRead"].(bool); ok {
		if isRead {
			updatedBook.Status = "Gelesen"
		} else {
			updatedBook.Status = "Ungelesen"
		}
	}

	if fiction, ok := requestData["fiction"].(bool); ok {
		updatedBook.Fiction = fiction
	} else if fictionStr, ok := requestData["fiction"].(string); ok {
		// Falls Fiction als String gesendet wird
		updatedBook.Fiction = fictionStr == "true" || fictionStr == "Fiction"
	}

	logger.Debug(fmt.Sprintf("updateBook: Verarbeitete Buchdaten: %+v", updatedBook))

	if err := db.Save(&updatedBook).Error; err != nil {
		logger.Error(fmt.Sprintf("updateBook: Datenbankfehler beim Speichern: %v", err))
		c.JSON(500, gin.H{"error": "Konnte Buch nicht aktualisieren"})
		return
	}

	// Erstelle Progress-History-Eintrag, wenn sich der Lesefortschritt geändert hat
	if oldProgress != updatedBook.ReadingProgress {
		change := updatedBook.ReadingProgress - oldProgress
		progressEntry := ProgressHistory{
			BookID:    updatedBook.ID,
			Page:      updatedBook.ReadingProgress,
			Change:    change,
			Date:      time.Now(),
			CreatedAt: time.Now(),
		}

		if err := db.Create(&progressEntry).Error; err != nil {
			logger.Error(fmt.Sprintf("updateBook: Konnte Progress-History nicht erstellen: %v", err))
			// Nicht kritisch, Buch-Update war erfolgreich
		}
	}

	logger.Info(fmt.Sprintf("updateBook: Buch erfolgreich aktualisiert - ID: %d, Titel: %s", updatedBook.ID, updatedBook.Title))
	c.JSON(200, updatedBook)
}

func deleteBook(c *gin.Context) {
	id := c.Param("id")

	// Erst das Buch finden, um den Cover-Pfad zu bekommen
	var book Book
	if err := db.First(&book, id).Error; err != nil {
		c.JSON(404, gin.H{"error": "Buch nicht gefunden"})
		return
	}

	// Cover-Datei löschen, falls vorhanden
	if book.CoverImage != "" {
		coverPath := filepath.Join("uploads", "covers", book.CoverImage)
		if _, err := os.Stat(coverPath); err == nil {
			if err := os.Remove(coverPath); err != nil {
				logger.Error(fmt.Sprintf("Konnte Cover-Datei nicht löschen: %v", err))
			} else {
				logger.Info(fmt.Sprintf("Cover-Datei gelöscht: %s", coverPath))
			}
		}
	}

	// Buch aus der Datenbank löschen
	if err := db.Delete(&Book{}, id).Error; err != nil {
		c.JSON(500, gin.H{"error": "Konnte Buch nicht löschen"})
		return
	}

	c.JSON(200, gin.H{"message": "Buch gelöscht"})
}

func uploadBookCover(c *gin.Context) {
	id := c.Param("id")

	// Prüfen ob das Buch existiert
	var book Book
	if err := db.First(&book, id).Error; err != nil {
		c.JSON(404, gin.H{"error": "Buch nicht gefunden"})
		return
	}

	// Datei aus dem Request lesen
	file, header, err := c.Request.FormFile("cover")
	if err != nil {
		c.JSON(400, gin.H{"error": "Keine Cover-Datei gefunden"})
		return
	}
	defer file.Close()

	// Dateierweiterung prüfen
	ext := strings.ToLower(filepath.Ext(header.Filename))
	if ext != ".jpg" && ext != ".jpeg" && ext != ".png" && ext != ".webp" {
		c.JSON(400, gin.H{"error": "Nur JPG, PNG und WebP Dateien sind erlaubt"})
		return
	}

	// Upload-Verzeichnis erstellen
	uploadDir := filepath.Join("uploads", "covers")
	if err := os.MkdirAll(uploadDir, 0755); err != nil {
		logger.Error(fmt.Sprintf("Konnte Upload-Verzeichnis nicht erstellen: %v", err))
		c.JSON(500, gin.H{"error": "Server-Fehler"})
		return
	}

	// Altes Cover löschen, falls vorhanden
	if book.CoverImage != "" {
		oldCoverPath := filepath.Join(uploadDir, book.CoverImage)
		if _, err := os.Stat(oldCoverPath); err == nil {
			if err := os.Remove(oldCoverPath); err != nil {
				logger.Error(fmt.Sprintf("Konnte altes Cover nicht löschen: %v", err))
			}
		}
	}

	// Neuen Dateinamen generieren
	filename := fmt.Sprintf("book_%s_%d%s", id, time.Now().Unix(), ext)
	filePath := filepath.Join(uploadDir, filename)

	// Datei speichern
	dst, err := os.Create(filePath)
	if err != nil {
		logger.Error(fmt.Sprintf("Konnte Cover-Datei nicht erstellen: %v", err))
		c.JSON(500, gin.H{"error": "Konnte Cover nicht speichern"})
		return
	}
	defer dst.Close()

	if _, err := io.Copy(dst, file); err != nil {
		logger.Error(fmt.Sprintf("Konnte Cover-Datei nicht kopieren: %v", err))
		c.JSON(500, gin.H{"error": "Konnte Cover nicht speichern"})
		return
	}

	// Buch in der Datenbank aktualisieren
	book.CoverImage = filename
	if err := db.Save(&book).Error; err != nil {
		logger.Error(fmt.Sprintf("Konnte Buch-Cover in Datenbank nicht aktualisieren: %v", err))
		// Hochgeladene Datei wieder löschen
		os.Remove(filePath)
		c.JSON(500, gin.H{"error": "Konnte Cover-Referenz nicht speichern"})
		return
	}

	logger.Info(fmt.Sprintf("Cover für Buch ID %s erfolgreich hochgeladen: %s", id, filename))
	c.JSON(200, gin.H{
		"message":     "Cover erfolgreich hochgeladen",
		"cover_image": filename,
		"book":        book,
	})
}

func uploadWishlistCover(c *gin.Context) {
	id := c.Param("id")

	// Prüfen ob das Wunschliste-Item existiert
	var wishlistItem Wishlist
	if err := db.First(&wishlistItem, id).Error; err != nil {
		c.JSON(404, gin.H{"error": "Wunschliste-Eintrag nicht gefunden"})
		return
	}

	// Datei aus dem Request lesen
	file, header, err := c.Request.FormFile("cover")
	if err != nil {
		c.JSON(400, gin.H{"error": "Keine Cover-Datei gefunden"})
		return
	}
	defer file.Close()

	// Dateierweiterung prüfen
	ext := strings.ToLower(filepath.Ext(header.Filename))
	if ext != ".jpg" && ext != ".jpeg" && ext != ".png" && ext != ".webp" {
		c.JSON(400, gin.H{"error": "Nur JPG, PNG und WebP Dateien sind erlaubt"})
		return
	}

	// Upload-Verzeichnis erstellen (gleicher Pfad wie bei Büchern)
	uploadDir := filepath.Join("uploads", "covers")
	if err := os.MkdirAll(uploadDir, 0755); err != nil {
		logger.Error(fmt.Sprintf("Konnte Upload-Verzeichnis nicht erstellen: %v", err))
		c.JSON(500, gin.H{"error": "Server-Fehler"})
		return
	}

	// Altes Cover löschen, falls vorhanden
	if wishlistItem.CoverImage != "" {
		oldCoverPath := filepath.Join(uploadDir, wishlistItem.CoverImage)
		if _, err := os.Stat(oldCoverPath); err == nil {
			if err := os.Remove(oldCoverPath); err != nil {
				logger.Error(fmt.Sprintf("Konnte altes Wunschliste-Cover nicht löschen: %v", err))
			}
		}
	}

	// Neuen Dateinamen generieren
	filename := fmt.Sprintf("wishlist_%s_%d%s", id, time.Now().Unix(), ext)
	filePath := filepath.Join(uploadDir, filename)

	// Datei speichern
	dst, err := os.Create(filePath)
	if err != nil {
		logger.Error(fmt.Sprintf("Konnte Wunschliste-Cover-Datei nicht erstellen: %v", err))
		c.JSON(500, gin.H{"error": "Konnte Cover nicht speichern"})
		return
	}
	defer dst.Close()

	if _, err := io.Copy(dst, file); err != nil {
		logger.Error(fmt.Sprintf("Konnte Wunschliste-Cover-Datei nicht kopieren: %v", err))
		c.JSON(500, gin.H{"error": "Konnte Cover nicht speichern"})
		return
	}

	// Wunschliste-Item in der Datenbank aktualisieren
	wishlistItem.CoverImage = filename
	if err := db.Save(&wishlistItem).Error; err != nil {
		logger.Error(fmt.Sprintf("Konnte Wunschliste-Cover in Datenbank nicht aktualisieren: %v", err))
		// Hochgeladene Datei wieder löschen
		os.Remove(filePath)
		c.JSON(500, gin.H{"error": "Konnte Cover-Referenz nicht speichern"})
		return
	}

	logger.Info(fmt.Sprintf("Cover für Wunschliste-Item ID %s erfolgreich hochgeladen: %s", id, filename))
	c.JSON(200, gin.H{
		"message":     "Cover erfolgreich hochgeladen",
		"cover_image": filename,
		"wishlist":    wishlistItem,
	})
}

// Wishlist Funktionen
func getWishlist(c *gin.Context) {
	var wishlist []Wishlist
	search := c.Query("search")

	query := db
	if search != "" {
		query = query.Where("title LIKE ? OR author LIKE ?", "%"+search+"%", "%"+search+"%")
	}

	if err := query.Find(&wishlist).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	c.JSON(200, wishlist)
}

func getWishlistItem(c *gin.Context) {
	id := c.Param("id")
	var item Wishlist

	if err := db.First(&item, id).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(404, gin.H{"error": "Wishlist-Item nicht gefunden"})
		} else {
			c.JSON(500, gin.H{"error": "Datenbankfehler"})
		}
		return
	}

	c.JSON(200, item)
}

func createWishlistItem(c *gin.Context) {
	var item Wishlist
	if err := c.ShouldBindJSON(&item); err != nil {
		c.JSON(400, gin.H{"error": fmt.Sprintf("Ungültige Daten: %v", err)})
		return
	}

	// Automatisches Erstellen des Verlags falls er nicht existiert (falls Verlag angegeben)
	if item.Publisher != "" {
		if err := ensurePublisherExists(item.Publisher); err != nil {
			logger.Error(fmt.Sprintf("createWishlistItem: Fehler beim Erstellen des Verlags: %v", err))
			c.JSON(500, gin.H{"error": fmt.Sprintf("Fehler beim Verarbeiten des Verlags: %v", err)})
			return
		}
	}

	if err := db.Create(&item).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	c.JSON(201, item)
}

func deleteWishlistItem(c *gin.Context) {
	id := c.Param("id")
	if err := db.Delete(&Wishlist{}, id).Error; err != nil {
		c.JSON(500, gin.H{"error": "Konnte Eintrag nicht löschen"})
		return
	}

	c.JSON(200, gin.H{"message": "Eintrag gelöscht"})
}

func buyWishlistItem(c *gin.Context) {
	id := c.Param("id")
	var wishlistItem Wishlist

	if err := db.First(&wishlistItem, id).Error; err != nil {
		c.JSON(404, gin.H{"error": "Eintrag nicht gefunden"})
		return
	}

	var request struct {
		Format string `json:"format"`
	}
	if err := c.ShouldBindJSON(&request); err != nil {
		c.JSON(400, gin.H{"error": "Ungültige Daten"})
		return
	}

	// Erstelle neues Buch aus Wunschlisteneintrag
	book := Book{
		Title:       wishlistItem.Title,
		Author:      wishlistItem.Author,
		Genre:       wishlistItem.Genre,
		Pages:       wishlistItem.Pages,
		Format:      request.Format,
		Publisher:   wishlistItem.Publisher,
		PublishDate: wishlistItem.PublishDate,
		Series:      wishlistItem.Series,
		Volume:      wishlistItem.Volume,
		CoverImage:  wishlistItem.CoverImage, // Cover automatisch übertragen
		Status:      "Ungelesen",
	}

	// Automatisches Erstellen des Verlags falls er nicht existiert (falls Verlag angegeben)
	if book.Publisher != "" {
		if err := ensurePublisherExists(book.Publisher); err != nil {
			logger.Error(fmt.Sprintf("buyWishlistItem: Fehler beim Erstellen des Verlags: %v", err))
			c.JSON(500, gin.H{"error": fmt.Sprintf("Fehler beim Verarbeiten des Verlags: %v", err)})
			return
		}
	}

	if err := db.Create(&book).Error; err != nil {
		c.JSON(500, gin.H{"error": "Konnte Buch nicht erstellen"})
		return
	}

	// Lösche Wunschlisteneintrag
	db.Delete(&wishlistItem)

	c.JSON(200, gin.H{"message": "Buch erfolgreich hinzugefügt", "book": book})
}

// Quotes Funktionen
func getQuotes(c *gin.Context) {
	var quotes []Quote
	search := c.Query("search")

	query := db
	if search != "" {
		query = query.Where("quote LIKE ? OR book LIKE ?", "%"+search+"%", "%"+search+"%")
	}

	if err := query.Find(&quotes).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	c.JSON(200, quotes)
}

func createQuote(c *gin.Context) {
	var quote Quote
	if err := c.ShouldBindJSON(&quote); err != nil {
		c.JSON(400, gin.H{"error": fmt.Sprintf("Ungültige Daten: %v", err)})
		return
	}

	if err := db.Create(&quote).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	c.JSON(201, quote)
}

func deleteQuote(c *gin.Context) {
	id := c.Param("id")
	if err := db.Delete(&Quote{}, id).Error; err != nil {
		c.JSON(500, gin.H{"error": "Konnte Zitat nicht löschen"})
		return
	}

	c.JSON(200, gin.H{"message": "Zitat gelöscht"})
}

// Stats Funktion
func getStats(c *gin.Context) {
	var totalBooks int64
	var readBooks int64
	var totalQuotes int64

	db.Model(&Book{}).Count(&totalBooks)
	db.Model(&Book{}).Where("status = ?", "Gelesen").Count(&readBooks)
	db.Model(&Quote{}).Count(&totalQuotes)

	var recentBooks []Book
	db.Order("created_at DESC").Limit(6).Find(&recentBooks)

	var currentlyReading []Book
	db.Where("status = ?", "Am Lesen").Order("updated_at DESC").Find(&currentlyReading)

	stats := gin.H{
		"totalBooks":       totalBooks,
		"readBooks":        readBooks,
		"totalQuotes":      totalQuotes,
		"recentBooks":      recentBooks,
		"currentlyReading": currentlyReading,
	}

	c.JSON(200, stats)
}

func getGenreStats(c *gin.Context) {
	var results []struct {
		Name  string `json:"name"`
		Count int64  `json:"count"`
	}

	db.Model(&Book{}).
		Select("genre as name, count(*) as count").
		Where("genre != ''").
		Group("genre").
		Order("count DESC").
		Scan(&results)

	c.JSON(200, results)
}

func getPublisherStats(c *gin.Context) {
	var results []struct {
		Name  string `json:"name"`
		Count int64  `json:"count"`
	}

	db.Model(&Book{}).
		Select("publisher as name, count(*) as count").
		Where("publisher != ''").
		Group("publisher").
		Order("count DESC").
		Scan(&results)

	c.JSON(200, results)
}

// Reading Goal Funktionen
func getReadingGoal(c *gin.Context) {
	var goal ReadingGoal

	// Versuche das bestehende Leseziel zu finden
	if err := db.First(&goal).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			// Kein Leseziel gefunden, gib Standardwerte zurück
			c.JSON(200, gin.H{
				"enabled": false,
				"current": 0,
				"target":  12,
			})
			return
		}
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	// Berechne aktuelle Anzahl gelesener Bücher in diesem Jahr
	var readCount int64
	currentYear := time.Now().Year()
	yearStart := time.Date(currentYear, 1, 1, 0, 0, 0, 0, time.UTC)
	yearEnd := time.Date(currentYear+1, 1, 1, 0, 0, 0, 0, time.UTC)

	db.Model(&Book{}).
		Where("status = ? AND updated_at >= ? AND updated_at < ?", "Gelesen", yearStart, yearEnd).
		Count(&readCount)

	c.JSON(200, gin.H{
		"enabled": goal.Enabled,
		"current": int(readCount),
		"target":  goal.Target,
	})
}

func updateReadingGoal(c *gin.Context) {
	var requestData struct {
		Enabled bool `json:"enabled"`
		Target  int  `json:"target"`
	}

	if err := c.ShouldBindJSON(&requestData); err != nil {
		c.JSON(400, gin.H{"error": fmt.Sprintf("Ungültige Daten: %v", err)})
		return
	}

	var goal ReadingGoal

	// Versuche das bestehende Leseziel zu finden
	if err := db.First(&goal).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			// Kein Leseziel gefunden, erstelle ein neues
			goal = ReadingGoal{
				Enabled:   requestData.Enabled,
				Target:    requestData.Target,
				Type:      "year",
				Current:   0,
				UpdatedAt: time.Now(),
			}

			if err := db.Create(&goal).Error; err != nil {
				c.JSON(500, gin.H{"error": "Konnte Leseziel nicht erstellen"})
				return
			}
		} else {
			c.JSON(500, gin.H{"error": "Datenbankfehler"})
			return
		}
	} else {
		// Aktualisiere bestehendes Leseziel
		goal.Enabled = requestData.Enabled
		goal.Target = requestData.Target
		goal.UpdatedAt = time.Now()

		if err := db.Save(&goal).Error; err != nil {
			c.JSON(500, gin.H{"error": "Konnte Leseziel nicht speichern"})
			return
		}
	}

	// Berechne aktuelle Anzahl gelesener Bücher in diesem Jahr
	var readCount int64
	currentYear := time.Now().Year()
	yearStart := time.Date(currentYear, 1, 1, 0, 0, 0, 0, time.UTC)
	yearEnd := time.Date(currentYear+1, 1, 1, 0, 0, 0, 0, time.UTC)

	db.Model(&Book{}).
		Where("status = ? AND updated_at >= ? AND updated_at < ?", "Gelesen", yearStart, yearEnd).
		Count(&readCount)

	c.JSON(200, gin.H{
		"message": "Leseziel erfolgreich aktualisiert",
		"enabled": goal.Enabled,
		"current": int(readCount),
		"target":  goal.Target,
	})
}

// Genre Funktionen
func getGenres(c *gin.Context) {
	var genres []Genre
	if err := db.Find(&genres).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	c.JSON(200, genres)
}

func createGenre(c *gin.Context) {
	var genre Genre
	if err := c.ShouldBindJSON(&genre); err != nil {
		c.JSON(400, gin.H{"error": fmt.Sprintf("Ungültige Daten: %v", err)})
		return
	}

	if err := db.Create(&genre).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	c.JSON(201, genre)
}

func deleteGenre(c *gin.Context) {
	id := c.Param("id")
	if err := db.Delete(&Genre{}, id).Error; err != nil {
		c.JSON(500, gin.H{"error": "Konnte Genre nicht löschen"})
		return
	}

	c.JSON(200, gin.H{"message": "Genre gelöscht"})
}

// Publisher Funktionen
func getPublishers(c *gin.Context) {
	var publishers []Publisher
	if err := db.Find(&publishers).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	c.JSON(200, publishers)
}

func createPublisher(c *gin.Context) {
	var publisher Publisher
	if err := c.ShouldBindJSON(&publisher); err != nil {
		c.JSON(400, gin.H{"error": fmt.Sprintf("Ungültige Daten: %v", err)})
		return
	}

	if err := db.Create(&publisher).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	c.JSON(201, publisher)
}

func deletePublisher(c *gin.Context) {
	id := c.Param("id")
	if err := db.Delete(&Publisher{}, id).Error; err != nil {
		c.JSON(500, gin.H{"error": "Konnte Verlag nicht löschen"})
		return
	}

	c.JSON(200, gin.H{"message": "Verlag gelöscht"})
}

func getProgressHistory(c *gin.Context) {
	id := c.Param("id")
	var history []ProgressHistory

	if err := db.Where("book_id = ?", id).Order("date DESC").Limit(20).Find(&history).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	c.JSON(200, history)
}

func moveCoverFromWishlistToBook(c *gin.Context) {
	wishlistId := c.Param("id")
	bookId := c.Param("book_id")

	// Wishlist-Item finden
	var wishlistItem Wishlist
	if err := db.First(&wishlistItem, wishlistId).Error; err != nil {
		c.JSON(404, gin.H{"error": "Wishlist-Item nicht gefunden"})
		return
	}

	// Buch finden
	var book Book
	if err := db.First(&book, bookId).Error; err != nil {
		c.JSON(404, gin.H{"error": "Buch nicht gefunden"})
		return
	}

	// Cover übertragen, wenn vorhanden
	if wishlistItem.CoverImage != "" {
		book.CoverImage = wishlistItem.CoverImage
		if err := db.Save(&book).Error; err != nil {
			c.JSON(500, gin.H{"error": "Konnte Cover nicht übertragen"})
			return
		}

		// Cover vom Wishlist-Item entfernen
		wishlistItem.CoverImage = ""
		db.Save(&wishlistItem)
	}

	c.JSON(200, gin.H{"message": "Cover erfolgreich übertragen"})
}

// Hilfsfunktion zum Erstellen eines Verlags falls er nicht existiert
func ensurePublisherExists(publisherName string) error {
	if publisherName == "" {
		return fmt.Errorf("verlagsname ist leer")
	}

	// Prüfe ob Verlag bereits existiert
	var existingPublisher Publisher
	if err := db.Where("name = ?", publisherName).First(&existingPublisher).Error; err == nil {
		// Verlag existiert bereits
		return nil
	}

	// Erstelle neuen Verlag
	newPublisher := Publisher{Name: publisherName}
	if err := db.Create(&newPublisher).Error; err != nil {
		logger.Error(fmt.Sprintf("Fehler beim Erstellen des Verlags '%s': %v", publisherName, err))
		return err
	}

	logger.Info(fmt.Sprintf("Neuer Verlag automatisch erstellt: %s", publisherName))
	return nil
}

func updateWishlistItem(c *gin.Context) {
	id := c.Param("id")
	var existingItem Wishlist

	if err := db.First(&existingItem, id).Error; err != nil {
		c.JSON(404, gin.H{"error": "Wunschliste-Eintrag nicht gefunden"})
		return
	}

	var requestData map[string]interface{}
	if err := c.ShouldBindJSON(&requestData); err != nil {
		logger.Error(fmt.Sprintf("updateWishlistItem: Fehler beim Parsen der JSON-Daten: %v", err))
		c.JSON(400, gin.H{"error": "Ungültige Daten"})
		return
	}

	// Erstelle ein neues Wishlist-Objekt basierend auf dem bestehenden Eintrag
	updatedItem := existingItem

	// Manuell die Felder aktualisieren, die im Request enthalten sind
	if title, ok := requestData["title"].(string); ok {
		updatedItem.Title = title
	}
	if author, ok := requestData["author"].(string); ok {
		updatedItem.Author = author
	}
	if genre, ok := requestData["genre"].(string); ok {
		updatedItem.Genre = genre
	}
	if publisher, ok := requestData["publisher"].(string); ok {
		updatedItem.Publisher = publisher
		// Automatisches Erstellen des Verlags falls er nicht existiert
		if publisher != "" {
			if err := ensurePublisherExists(publisher); err != nil {
				logger.Error(fmt.Sprintf("updateWishlistItem: Fehler beim Erstellen des Verlags: %v", err))
				c.JSON(500, gin.H{"error": fmt.Sprintf("Fehler beim Verarbeiten des Verlags: %v", err)})
				return
			}
		}
	}
	if publishDate, ok := requestData["publish_date"].(string); ok {
		updatedItem.PublishDate = publishDate
	}
	if series, ok := requestData["series"].(string); ok {
		updatedItem.Series = series
	}

	// Numerische Felder
	if pages, ok := requestData["pages"].(float64); ok {
		updatedItem.Pages = int(pages)
	}
	if volume, ok := requestData["volume"].(float64); ok {
		updatedItem.Volume = int(volume)
	}

	if err := db.Save(&updatedItem).Error; err != nil {
		logger.Error(fmt.Sprintf("updateWishlistItem: Datenbankfehler beim Speichern: %v", err))
		c.JSON(500, gin.H{"error": "Konnte Wunschliste-Eintrag nicht aktualisieren"})
		return
	}

	logger.Info(fmt.Sprintf("updateWishlistItem: Wunschliste-Eintrag erfolgreich aktualisiert - ID: %d, Titel: %s", updatedItem.ID, updatedItem.Title))
	c.JSON(200, updatedItem)
}

func updateBookStatus(c *gin.Context) {
	id := c.Param("id")
	var book Book

	if err := db.First(&book, id).Error; err != nil {
		c.JSON(404, gin.H{"error": "Buch nicht gefunden"})
		return
	}

	var request struct {
		Status string `json:"status"`
	}

	if err := c.ShouldBindJSON(&request); err != nil {
		c.JSON(400, gin.H{"error": "Ungültige Anfrage"})
		return
	}

	// Validiere den Status
	validStatuses := []string{"Ungelesen", "Am Lesen", "Gelesen"}
	isValid := false
	for _, validStatus := range validStatuses {
		if request.Status == validStatus {
			isValid = true
			break
		}
	}

	if !isValid {
		c.JSON(400, gin.H{"error": "Ungültiger Status. Erlaubt sind: Ungelesen, Am Lesen, Gelesen"})
		return
	}

	// Status aktualisieren
	book.Status = request.Status

	if err := db.Save(&book).Error; err != nil {
		logger.Error(fmt.Sprintf("updateBookStatus: Fehler beim Speichern: %v", err))
		c.JSON(500, gin.H{"error": "Fehler beim Speichern"})
		return
	}

	logger.Info(fmt.Sprintf("updateBookStatus: Status von Buch %d auf '%s' geändert", book.ID, request.Status))
	c.JSON(200, gin.H{"message": "Status erfolgreich geändert", "book": book})
}

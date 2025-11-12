package main

import (
	"context"
	"crypto/tls"
	"embed"
	"encoding/json"
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
	"sync"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"
	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/huin/goupnp/dcps/internetgateway2"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// App Konstanten
const (
	AppVersion = "1.0.6"
	AppName    = "Reading Diary"
	AppAuthor  = "TheMRX - Pascal Keller"
)

//go:embed web/*
var webFiles embed.FS

// Database Models
type Book struct {
	ID              uint      `json:"id" gorm:"primaryKey"`
	Title           string    `json:"title" gorm:"not null"`
	Author          string    `json:"author" gorm:"not null"`
	ISBN            string    `json:"isbn" gorm:"index"` // ISBN Feld hinzugefügt
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
	ISBN        string    `json:"isbn" gorm:"index"` // ISBN Feld hinzugefügt
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

type ServerSettings struct {
	ID        uint      `json:"id" gorm:"primaryKey"`
	Key       string    `json:"key" gorm:"unique;not null"`
	Value     string    `json:"value"`
	UpdatedAt time.Time `json:"updated_at"`
}

// ExternalConfig speichert Konfiguration für externe Freigabe
type ExternalConfig struct {
	Enabled       bool   `json:"enabled"`
	DuckDNSDomain string `json:"duckdns_domain"`
	DuckDNSToken  string `json:"duckdns_token"`
}

// Global variables
var (
	db             *gorm.DB
	serverPort     = 7443
	serverPassword = "admin123"
	serverRunning  = false
	httpServer     *http.Server
	ipAddresses    []string

	// External Access
	externalEnabled   = false
	duckDNSDomain     = ""
	duckDNSToken      = ""
	duckDNSUpdateStop chan bool
	upnpActive        = false
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

		// Nur wichtige Anfragen loggen (nicht statische Dateien und API-Health-Checks)
		shouldLog := true
		path := c.Request.URL.Path
		method := c.Request.Method

		// Filtere häufige, unwichtige Anfragen heraus
		if strings.HasPrefix(path, "/static/") ||
			strings.HasPrefix(path, "/uploads/") ||
			(path == "/api/stats" && method == "GET") ||
			(path == "/api/reading-goal" && method == "GET") {
			shouldLog = false
		}

		// Request Info (nur für wichtige Anfragen)
		if shouldLog && logger != nil {
			logger.Info(fmt.Sprintf("→ %s %s from %s", method, path, c.ClientIP()))
		}

		c.Next()

		// Response Info (nur für Fehler oder wichtige Anfragen)
		if logger != nil {
			duration := time.Since(start)
			status := c.Writer.Status()
			size := c.Writer.Size()

			// Nur bei Fehlern oder wichtigen Anfragen loggen
			if status >= 400 || shouldLog {
				statusLevel := "INFO"
				if status >= 400 && status < 500 {
					statusLevel = "WARN"
				} else if status >= 500 {
					statusLevel = "ERROR"
				}

				logger.Log(statusLevel, fmt.Sprintf("← %d %s (%v) %d bytes",
					status, path, duration, size))
			}
		}
	}
}

// HTTPSRedirectMiddleware leitet HTTP→HTTPS um (nur wenn externe Freigabe aktiv)
func HTTPSRedirectMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		// Nur umleiten wenn externe Freigabe aktiviert ist
		if !externalEnabled {
			c.Next()
			return
		}

		// Prüfe ob Anfrage über HTTP kam (nicht HTTPS)
		if c.Request.TLS == nil && c.GetHeader("X-Forwarded-Proto") != "https" {
			// Baue HTTPS URL
			host := c.Request.Host
			if host == "" {
				host = c.Request.Header.Get("Host")
			}

			// Verwende DuckDNS Domain wenn verfügbar
			if duckDNSDomain != "" {
				domain := duckDNSDomain
				if !strings.HasSuffix(domain, ".duckdns.org") {
					domain = domain + ".duckdns.org"
				}
				host = domain + ":7443"
			}

			httpsURL := "https://" + host + c.Request.RequestURI

			logger.Info(fmt.Sprintf("HTTP→HTTPS Redirect: %s → %s", c.Request.URL.String(), httpsURL))
			c.Redirect(http.StatusMovedPermanently, httpsURL)
			c.Abort()
			return
		}

		c.Next()
	}
}

// GUI Components
type ServerGUI struct {
	app             fyne.App
	window          fyne.Window
	statusLabel     *widget.Label
	portEntry       *widget.Entry
	passwordEntry   *widget.Entry
	startButton     *widget.Button
	logText         *widget.Label
	logList         *widget.List
	logScroll       *container.Scroll
	logEntries      []string
	autoScrollLog   bool
	autoScrollCheck *widget.Check
	ipContainer     *fyne.Container
	urlSelect       *widget.Select
	uptimeLabel     *widget.Label
	startTime       time.Time

	// External Access GUI Elements
	externalCheckbox    *widget.Check
	duckDNSDomainEntry  *widget.Entry
	duckDNSTokenEntry   *widget.Entry
	externalStatusLabel *widget.Label
	externalSaveButton  *widget.Button
}

// WebSocket structures
type Client struct {
	hub  *Hub
	conn *websocket.Conn
	send chan []byte
}

type Hub struct {
	clients    map[*Client]bool
	broadcast  chan []byte
	register   chan *Client
	unregister chan *Client
	mutex      sync.RWMutex
}

type WSMessage struct {
	Type    string      `json:"type"`
	Payload interface{} `json:"payload"`
}

var hub *Hub
var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return true // Allow all origins for local development
	},
}

func newHub() *Hub {
	return &Hub{
		broadcast:  make(chan []byte, 256),
		register:   make(chan *Client),
		unregister: make(chan *Client),
		clients:    make(map[*Client]bool),
	}
}

func (h *Hub) run() {
	for {
		select {
		case client := <-h.register:
			h.mutex.Lock()
			h.clients[client] = true
			h.mutex.Unlock()
			fmt.Printf("[WebSocket] Client connected. Total clients: %d\n", len(h.clients))

		case client := <-h.unregister:
			h.mutex.Lock()
			if _, ok := h.clients[client]; ok {
				delete(h.clients, client)
				close(client.send)
			}
			h.mutex.Unlock()
			fmt.Printf("[WebSocket] Client disconnected. Total clients: %d\n", len(h.clients))

		case message := <-h.broadcast:
			h.mutex.RLock()
			for client := range h.clients {
				select {
				case client.send <- message:
				default:
					close(client.send)
					delete(h.clients, client)
				}
			}
			h.mutex.RUnlock()
		}
	}
}

func (c *Client) readPump() {
	defer func() {
		c.hub.unregister <- c
		c.conn.Close()
	}()

	c.conn.SetReadDeadline(time.Now().Add(60 * time.Second))
	c.conn.SetPongHandler(func(string) error {
		c.conn.SetReadDeadline(time.Now().Add(60 * time.Second))
		return nil
	})

	for {
		_, _, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				fmt.Printf("[WebSocket] Error: %v\n", err)
			}
			break
		}
	}
}

func (c *Client) writePump() {
	ticker := time.NewTicker(54 * time.Second)
	defer func() {
		ticker.Stop()
		c.conn.Close()
	}()

	for {
		select {
		case message, ok := <-c.send:
			c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if !ok {
				c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}

			w, err := c.conn.NextWriter(websocket.TextMessage)
			if err != nil {
				return
			}
			w.Write(message)

			if err := w.Close(); err != nil {
				return
			}

		case <-ticker.C:
			c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

func broadcastEvent(eventType string, payload interface{}) {
	if hub == nil {
		return
	}

	message := WSMessage{
		Type:    eventType,
		Payload: payload,
	}

	jsonData, err := json.Marshal(message)
	if err != nil {
		fmt.Printf("[WebSocket] Error marshaling message: %v\n", err)
		return
	}

	hub.broadcast <- jsonData
}

func handleWebSocket(c *gin.Context) {
	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		fmt.Printf("[WebSocket] Upgrade error: %v\n", err)
		return
	}

	client := &Client{
		hub:  hub,
		conn: conn,
		send: make(chan []byte, 256),
	}

	client.hub.register <- client

	go client.writePump()
	go client.readPump()
}

// ============================================================================
// UPnP Port-Forwarding Functions
// ============================================================================

// getLocalIP ermittelt die lokale IP-Adresse
func getLocalIP() string {
	interfaces, err := net.Interfaces()
	if err != nil {
		return ""
	}

	var candidates []string

	for _, iface := range interfaces {
		// Nur aktive, nicht-Loopback Interfaces
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

			if ipv4 := ip.To4(); ipv4 != nil {
				ipStr := ipv4.String()

				// Ignoriere APIPA-Adressen (169.254.x.x)
				if strings.HasPrefix(ipStr, "169.254.") {
					continue
				}

				candidates = append(candidates, ipStr)
			}
		}
	}

	// Wenn nur eine IP gefunden wurde, diese zurückgeben
	if len(candidates) == 1 {
		return candidates[0]
	}

	// Bei mehreren IPs: Bevorzuge höhere dritte Oktette in 192.168.x.x
	// (z.B. 192.168.31.x vor 192.168.1.x, da oft Router-Netze niedriger sind)
	var best192168 string
	var best192168Third int

	for _, ip := range candidates {
		if strings.HasPrefix(ip, "192.168.") {
			parts := strings.Split(ip, ".")
			if len(parts) == 4 {
				third, _ := strconv.Atoi(parts[2])
				// Nehme die IP mit dem höchsten dritten Oktett (wahrscheinlich Haupt-Netzwerk)
				if third > best192168Third {
					best192168Third = third
					best192168 = ip
				}
			}
		}
	}

	if best192168 != "" {
		return best192168
	}

	// Fallback: Erste gefundene IP
	if len(candidates) > 0 {
		return candidates[0]
	}

	return ""
}

// setupUPnP aktiviert Port-Forwarding für Port 7443
func setupUPnP(logger Logger) (externalIP string, err error) {
	logger.Info("Suche nach UPnP-fähigem Router...")

	// Router-Gateway finden
	clients, _, err := internetgateway2.NewWANIPConnection1Clients()
	if err != nil || len(clients) == 0 {
		logger.Warning("Kein UPnP-Router gefunden - versuche WANIPConnection2...")

		// Fallback zu WANIPConnection2
		clients2, _, err2 := internetgateway2.NewWANIPConnection2Clients()
		if err2 != nil || len(clients2) == 0 {
			return "", fmt.Errorf("kein UPnP-fähiger Router gefunden")
		}

		// Verwende WANIPConnection2
		return setupUPnPWithClient2(clients2[0], logger)
	}

	client := clients[0]
	localIP := getLocalIP()

	if localIP == "" {
		return "", fmt.Errorf("lokale IP-Adresse konnte nicht ermittelt werden")
	}

	logger.Info(fmt.Sprintf("Lokale IP: %s", localIP))

	// Port 7443 für HTTPS - mit aggressiver Bereinigung
	logger.Info("Öffne Port 7443 für HTTPS...")

	// Liste alle bestehenden Mappings und lösche Port 7443
	logger.Info("Suche nach bestehenden Port 7443 Mappings...")
	for i := uint16(0); i < 50; i++ {
		// Versuche, Mapping-Info abzurufen (GenericPortMappingEntry)
		_, intPort, protocol, _, _, _, _, _, err := client.GetGenericPortMappingEntry(i)
		if err != nil {
			// Keine weiteren Mappings
			break
		}

		if intPort == 7443 && protocol == "TCP" {
			logger.Info(fmt.Sprintf("Gefunden: Mapping #%d für Port 7443/TCP - lösche...", i))
			client.DeletePortMapping("", uint16(7443), "TCP")
			time.Sleep(500 * time.Millisecond)
		}
	}

	// Zusätzlich: Direkte Löschversuche
	logger.Info("Bereinige Port 7443 Mappings...")
	for i := 0; i < 3; i++ {
		client.DeletePortMapping("", uint16(7443), "TCP")
		time.Sleep(500 * time.Millisecond)
	}

	// Erstelle neues Mapping
	logger.Info("Erstelle neues Port 7443 Mapping...")
	err = client.AddPortMapping(
		"",                    // Remote Host
		uint16(7443),          // External Port
		"TCP",                 // Protocol
		uint16(7443),          // Internal Port
		localIP,               // Internal Client
		true,                  // Enabled
		"Reading Diary HTTPS", // Description
		0,                     // Lease Duration
	)
	if err != nil {
		logger.Error(fmt.Sprintf("Port 7443 Mapping fehlgeschlagen: %v", err))
		return "", fmt.Errorf("port 7443 mapping failed: %v", err)
	}

	logger.Info("Port 7443 erfolgreich geöffnet")

	// Externe IP abrufen
	externalIP, err = client.GetExternalIPAddress()
	if err != nil {
		// Fallback: Externe IP wird von DuckDNS ermittelt
		logger.Warning(fmt.Sprintf("Externe IP vom Router nicht verfügbar (Error 501): %v", err))
		logger.Info("Externe IP wird automatisch von DuckDNS ermittelt")
		externalIP = "auto" // Marker, dass DuckDNS die IP ermittelt
	} else {
		logger.Info(fmt.Sprintf("Externe IP: %s", externalIP))
	}

	upnpActive = true
	return externalIP, nil
}

// setupUPnPWithClient2 ist ein Fallback für WANIPConnection2
func setupUPnPWithClient2(client *internetgateway2.WANIPConnection2, logger Logger) (string, error) {
	localIP := getLocalIP()

	if localIP == "" {
		return "", fmt.Errorf("lokale IP-Adresse konnte nicht ermittelt werden")
	}

	logger.Info(fmt.Sprintf("Lokale IP: %s", localIP))

	// Port 7443 für HTTPS - erst alte Mappings löschen
	logger.Info("Öffne Port 7443 für HTTPS...")

	// Liste alle bestehenden Mappings und lösche Port 7443
	logger.Info("Suche nach bestehenden Port 7443 Mappings...")
	for i := uint16(0); i < 50; i++ {
		// Versuche, Mapping-Info abzurufen
		_, intPort, protocol, _, _, _, _, _, err := client.GetGenericPortMappingEntry(i)
		if err != nil {
			// Keine weiteren Mappings
			break
		}

		if intPort == 7443 && protocol == "TCP" {
			logger.Info(fmt.Sprintf("Gefunden: Mapping #%d für Port 7443/TCP - lösche...", i))
			client.DeletePortMapping("", uint16(7443), "TCP")
			time.Sleep(500 * time.Millisecond)
		}
	}

	// Zusätzlich: Direkte Löschversuche
	logger.Info("Bereinige Port 7443 Mappings...")
	for i := 0; i < 3; i++ {
		client.DeletePortMapping("", uint16(7443), "TCP")
		time.Sleep(500 * time.Millisecond)
	}

	// Erstelle neues Mapping
	logger.Info("Erstelle neues Port 7443 Mapping...")
	err := client.AddPortMapping(
		"", uint16(7443), "TCP", uint16(7443), localIP, true, "Reading Diary HTTPS", 0,
	)
	if err != nil {
		// Detaillierter Fehler
		logger.Error(fmt.Sprintf("Port 7443 Mapping fehlgeschlagen: %v", err))
		return "", fmt.Errorf("port 7443 mapping failed: %v", err)
	}

	// Externe IP abrufen
	externalIP, err := client.GetExternalIPAddress()
	if err != nil {
		// Fallback: Externe IP wird von DuckDNS ermittelt
		logger.Warning(fmt.Sprintf("Externe IP vom Router nicht verfügbar (Error 501): %v", err))
		logger.Info("Externe IP wird automatisch von DuckDNS ermittelt")
		externalIP = "auto" // Marker, dass DuckDNS die IP ermittelt
	} else {
		logger.Info(fmt.Sprintf("Externe IP: %s", externalIP))
	}

	upnpActive = true
	return externalIP, nil
}

// removeUPnP entfernt Port-Forwarding
func removeUPnP(logger Logger) error {
	if !upnpActive {
		return nil
	}

	logger.Info("Schließe UPnP Port-Forwarding...")

	clients, _, err := internetgateway2.NewWANIPConnection1Clients()
	if err != nil || len(clients) == 0 {
		// Fallback zu WANIPConnection2
		clients2, _, err2 := internetgateway2.NewWANIPConnection2Clients()
		if err2 != nil || len(clients2) == 0 {
			return nil // Kein Router gefunden, nichts zu tun
		}

		// Port 7443 schließen
		clients2[0].DeletePortMapping("", uint16(7443), "TCP")

		logger.Info("UPnP Port 7443 geschlossen")
		upnpActive = false
		return nil
	}

	client := clients[0]

	// Port 7443 schließen
	err = client.DeletePortMapping("", uint16(7443), "TCP")
	if err != nil {
		logger.Warning(fmt.Sprintf("Port 7443 konnte nicht geschlossen werden: %v", err))
	}

	logger.Info("UPnP Port 7443 geschlossen")
	upnpActive = false

	return nil
}

// ============================================================================
// DuckDNS Functions
// ============================================================================

// updateDuckDNS aktualisiert die IP-Adresse bei DuckDNS
func updateDuckDNS(domain, token, ip string, logger Logger) error {
	// Domain ohne .duckdns.org
	domain = strings.TrimSuffix(domain, ".duckdns.org")

	// Wenn IP leer oder "auto", DuckDNS ermittelt automatisch die externe IP
	if ip == "" || ip == "auto" {
		ip = ""
	}

	url := fmt.Sprintf("https://www.duckdns.org/update?domains=%s&token=%s&ip=%s", domain, token, ip)

	// HTTP Client mit Timeout
	client := &http.Client{
		Timeout: 15 * time.Second,
	}

	resp, err := client.Get(url)
	if err != nil {
		return fmt.Errorf("DuckDNS Update fehlgeschlagen: %v", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("DuckDNS Antwort konnte nicht gelesen werden: %v", err)
	}

	response := strings.TrimSpace(string(body))

	if response != "OK" {
		// "KO" bedeutet ungültiger Token oder Domain
		if response == "KO" {
			return fmt.Errorf("DuckDNS Update fehlgeschlagen: Ungültiger Token oder Domain existiert nicht")
		}
		return fmt.Errorf("DuckDNS Update fehlgeschlagen: %s", response)
	}

	if ip == "" {
		logger.Debug(fmt.Sprintf("DuckDNS Update erfolgreich: %s (IP automatisch ermittelt)", domain))
	} else {
		logger.Debug(fmt.Sprintf("DuckDNS Update erfolgreich: %s -> %s", domain, ip))
	}
	return nil
}

// startDuckDNSUpdater startet den automatischen DuckDNS Update Timer
func startDuckDNSUpdater(domain, token, ip string, logger Logger) {
	// Initial update
	if err := updateDuckDNS(domain, token, ip, logger); err != nil {
		logger.Warning(fmt.Sprintf("Initiales DuckDNS Update fehlgeschlagen: %v", err))
	} else {
		logger.Info("DuckDNS erfolgreich aktualisiert")
	}

	// Stop channel erstellen
	duckDNSUpdateStop = make(chan bool)

	// Update alle 5 Minuten
	ticker := time.NewTicker(5 * time.Minute)

	go func() {
		for {
			select {
			case <-ticker.C:
				// IP könnte sich geändert haben, neu ermitteln
				currentIP := ip

				// Versuche externe IP zu ermitteln (falls UPnP aktiv)
				if upnpActive {
					clients, _, err := internetgateway2.NewWANIPConnection1Clients()
					if err == nil && len(clients) > 0 {
						if extIP, err := clients[0].GetExternalIPAddress(); err == nil {
							currentIP = extIP
						}
					}
				}

				if err := updateDuckDNS(domain, token, currentIP, logger); err != nil {
					logger.Warning(fmt.Sprintf("DuckDNS Update fehlgeschlagen: %v", err))
				} else {
					logger.Debug("DuckDNS Update erfolgreich")
				}

			case <-duckDNSUpdateStop:
				ticker.Stop()
				logger.Info("DuckDNS Updater gestoppt")
				return
			}
		}
	}()
}

// stopDuckDNSUpdater stoppt den DuckDNS Update Timer
func stopDuckDNSUpdater() {
	if duckDNSUpdateStop != nil {
		close(duckDNSUpdateStop)
		duckDNSUpdateStop = nil
	}
}

// ============================================================================
// Let's Encrypt / HTTPS Functions
// ============================================================================

// ============================================================================
// Config Functions
// ============================================================================

// loadExternalConfig lädt die externe Freigabe Konfiguration aus der Datenbank
func loadExternalConfig() ExternalConfig {
	if db == nil {
		// Datenbank noch nicht initialisiert
		return ExternalConfig{
			Enabled:       false,
			DuckDNSDomain: "",
			DuckDNSToken:  "",
		}
	}

	enabled := getServerSetting("external_enabled", "false")
	domain := getServerSetting("external_duckdns_domain", "")
	token := getServerSetting("external_duckdns_token", "")

	return ExternalConfig{
		Enabled:       enabled == "true",
		DuckDNSDomain: domain,
		DuckDNSToken:  token,
	}
}

// saveExternalConfig speichert die externe Freigabe Konfiguration in der Datenbank
func saveExternalConfig(config ExternalConfig) error {
	if db == nil {
		return fmt.Errorf("datenbank nicht initialisiert")
	}

	enabledStr := "false"
	if config.Enabled {
		enabledStr = "true"
	}

	if err := setServerSetting("external_enabled", enabledStr); err != nil {
		return err
	}

	if err := setServerSetting("external_duckdns_domain", config.DuckDNSDomain); err != nil {
		return err
	}

	if err := setServerSetting("external_duckdns_token", config.DuckDNSToken); err != nil {
		return err
	}

	return nil
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

	// Log - ZUERST initialisieren
	g.logText = widget.NewLabel("")
	g.logText.Wrapping = fyne.TextWrapWord
	g.logText.Alignment = fyne.TextAlignLeading
	g.logText.TextStyle = fyne.TextStyle{Monospace: true}

	// Log-Liste für klickbare Einträge
	g.logEntries = []string{}
	g.autoScrollLog = true // Standard: Auto-Scroll aktiv

	g.logList = widget.NewList(
		func() int {
			return len(g.logEntries)
		},
		func() fyne.CanvasObject {
			label := widget.NewLabel("")
			label.Wrapping = fyne.TextWrapBreak
			label.Truncation = fyne.TextTruncateOff
			return label
		},
		func(id widget.ListItemID, obj fyne.CanvasObject) {
			label := obj.(*widget.Label)
			if id < len(g.logEntries) {
				label.SetText(g.logEntries[id])
			}
		},
	)

	// Scroll-Container für Log
	g.logScroll = container.NewScroll(g.logList)

	// Klick auf Log-Eintrag kopiert ihn
	g.logList.OnSelected = func(id widget.ListItemID) {
		if id < len(g.logEntries) {
			entry := g.logEntries[id]
			g.window.Clipboard().SetContent(entry)
			go func() {
				time.Sleep(10 * time.Second)
				g.logList.UnselectAll()
			}()
		}
	}

	// JETZT ERST Logger initialisieren, nachdem logText bereit ist
	logger = NewCombinedLogger(g)

	logger.Info("GUI-System initialisiert")
	logger.Info(fmt.Sprintf("%s v%s - Coded by %s", AppName, AppVersion, AppAuthor))

	// Datenbank initialisieren um Settings zu laden
	if err := initDatabase(); err != nil {
		logger.Error(fmt.Sprintf("Fehler beim Initialisieren der Datenbank: %v", err))
	} else {
		// Lade gespeichertes Passwort aus Datenbank
		savedPassword := getServerSetting("server_password", "admin123")
		if savedPassword != "admin123" {
			serverPassword = savedPassword
			g.passwordEntry.SetText(serverPassword)
			logger.Info("Gespeichertes Passwort aus Datenbank geladen")
		}
	}

	// URL Select Dropdown
	g.urlSelect = widget.NewSelect([]string{"Server nicht gestartet"}, func(selected string) {
		// Callback wird bei Auswahl ausgeführt (optional für später)
	})
	g.urlSelect.PlaceHolder = "Wähle URL zum Öffnen..."

	// IP-Adressen Container (für Backup, falls gebraucht)
	g.ipContainer = container.NewVBox()

	// Layout - Kompakt oben, großer Log unten
	settingsCard := widget.NewCard("Server Einstellungen", "", container.NewVBox(
		widget.NewLabel("Port: 7443"),
		widget.NewFormItem("Passwort:", g.passwordEntry).Widget,
		g.startButton,
	))

	statusCard := widget.NewCard("Server Status", "", container.NewVBox(
		g.statusLabel,
		g.uptimeLabel,
	))

	// URLs kompakt: Dropdown links, Buttons rechts
	urlCard := widget.NewCard("Verfügbare URLs", "", container.NewBorder(
		nil, nil, nil,
		container.NewVBox(
			widget.NewButton("Öffnen", g.openSelectedURL),
			widget.NewButton("Aktualisieren", g.refreshIPAddresses),
		),
		container.NewVBox(
			widget.NewLabel("URL auswählen:"),
			g.urlSelect,
		),
	))

	// Oberer Bereich: 3 Cards nebeneinander (kompakt)
	topContainer := container.NewGridWithColumns(3,
		settingsCard,
		statusCard,
		urlCard,
	)

	// Auto-Scroll Checkbox
	g.autoScrollCheck = widget.NewCheck("Auto-Scroll", func(checked bool) {
		g.autoScrollLog = checked
	})
	g.autoScrollCheck.SetChecked(true)

	logScrollContainer := container.NewBorder(
		container.NewHBox(
			widget.NewLabel("Server Log & Aktivitäten (Klick auf Zeile zum Kopieren)"),
			widget.NewSeparator(),
			widget.NewButton("Gesamten Log kopieren", func() {
				fullLog := strings.Join(g.logEntries, "\n")
				g.window.Clipboard().SetContent(fullLog)
				g.addLog("Gesamter Log in Zwischenablage kopiert")
			}),
			widget.NewButton("Log löschen", func() {
				g.logEntries = []string{}
				g.logList.Refresh()
			}),
			g.autoScrollCheck,
		),
		nil, nil, nil,
		g.logScroll,
	)

	// ========================================================================
	// Externe Freigabe Tab
	// ========================================================================

	// Lade aktuelle Konfiguration
	extConfig := loadExternalConfig()

	g.duckDNSDomainEntry = widget.NewEntry()
	g.duckDNSDomainEntry.SetPlaceHolder("z.B. meinbuch")
	g.duckDNSDomainEntry.SetText(extConfig.DuckDNSDomain)

	g.duckDNSTokenEntry = widget.NewPasswordEntry()
	g.duckDNSTokenEntry.SetPlaceHolder("DuckDNS Token")
	g.duckDNSTokenEntry.SetText(extConfig.DuckDNSToken)

	g.externalCheckbox = widget.NewCheck("Externe Freigabe aktivieren (HTTPS)", func(checked bool) {
		if checked {
			g.duckDNSDomainEntry.Enable()
			g.duckDNSTokenEntry.Enable()
		} else {
			g.duckDNSDomainEntry.Disable()
			g.duckDNSTokenEntry.Disable()
		}
	})
	g.externalCheckbox.SetChecked(extConfig.Enabled)

	// Initial state
	if !extConfig.Enabled {
		g.duckDNSDomainEntry.Disable()
		g.duckDNSTokenEntry.Disable()
	}

	g.externalStatusLabel = widget.NewLabel("Status: Nicht aktiv")
	if extConfig.Enabled {
		g.externalStatusLabel.SetText("Status: Konfiguriert (Server neu starten)")
	}

	g.externalSaveButton = widget.NewButton("Konfiguration speichern", g.saveExternalConfig)

	duckDNSHelpButton := widget.NewButton("DuckDNS Anleitung", func() {
		dialog.ShowInformation("DuckDNS Setup",
			"1. Gehe zu https://www.duckdns.org/\n"+
				"2. Login mit Google/GitHub\n"+
				"3. Erstelle eine Domain (z.B. 'meinbuch')\n"+
				"4. Kopiere deinen Token\n"+
				"5. Trage Domain + Token hier ein\n"+
				"6. Speichern & Server neu starten\n\n",
			g.window)
	})

	externalForm := container.NewVBox(
		widget.NewCard("🌐 Externe Freigabe", "Server von außen per HTTPS erreichbar machen",
			container.NewVBox(
				g.externalCheckbox,
				widget.NewSeparator(),
				widget.NewLabel("DuckDNS Konfiguration:"),
				widget.NewFormItem("Domain (ohne .duckdns.org):", g.duckDNSDomainEntry).Widget,
				widget.NewFormItem("DuckDNS Token:", g.duckDNSTokenEntry).Widget,
				container.NewHBox(g.externalSaveButton, duckDNSHelpButton),
				widget.NewSeparator(),
				g.externalStatusLabel,
			),
		),
		widget.NewCard("Funktionsweise", "",
			widget.NewLabel(
				"Wenn aktiviert:\n"+
					"• UPnP öffnet automatisch Port 7443 am Router\n"+
					"• DuckDNS aktualisiert alle 5 Min. deine IP\n"+
					"• Let's Encrypt holt automatisch HTTPS-Zertifikat (DNS-01)\n"+
					"• Verwendet DuckDNS TXT-Records für Verifizierung\n"+
					"• Server ist extern erreichbar unter:\n"+
					"  https://deinedomain.duckdns.org:7443\n\n"+
					"• WICHTIG - NAT Loopback Problem:\n"+
					"• DuckDNS URL funktioniert NUR von extern!\n"+
					"• Im lokalen Netzwerk: Nutze lokale IP (https://192.168.x.x:7443)\n"+
					"• Router unterstützt meist kein NAT Hairpinning\n\n"+
					"Wenn deaktiviert:\n"+
					"• Server läuft nur lokal auf Port 7443\n"+
					"• Keine Router-Konfiguration nötig",
			),
		),
		widget.NewCard("⚠️ Voraussetzungen", "",
			widget.NewLabel(
				"• Router muss UPnP unterstützen (nur für Port 7443)\n"+
					"• Kostenlose DuckDNS Domain + Token benötigt\n"+
					"• Server muss nach Änderungen neu gestartet werden\n"+
					"• Zertifikats-Erstellung dauert 1-2 Minuten (DNS-01)",
			),
		),
	)

	// ========================================================================
	// Tabs erstellen
	// ========================================================================

	// Server Tab mit optimiertem Layout: Einstellungen oben kompakt, Log nimmt mehr Platz
	serverTab := container.NewBorder(
		widget.NewCard("", "", topContainer),
		nil, nil, nil,
		widget.NewCard("", "", logScrollContainer),
	)

	tabs := container.NewAppTabs(
		container.NewTabItem("Server", serverTab),
		container.NewTabItem("Externe Freigabe", container.NewScroll(externalForm)),
	)

	creditsLabel := widget.NewRichTextFromMarkdown(fmt.Sprintf("**%s v%s**\n\nCoded by %s", AppName, AppVersion, AppAuthor))
	creditsLabel.Wrapping = fyne.TextWrapWord

	mainContainer := container.NewBorder(
		nil,
		container.NewVBox(
			widget.NewSeparator(),
			creditsLabel,
		),
		nil, nil,
		tabs,
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

func (g *ServerGUI) saveExternalConfig() {
	logger.Info("Speichere externe Freigabe Konfiguration...")

	config := ExternalConfig{
		Enabled:       g.externalCheckbox.Checked,
		DuckDNSDomain: strings.TrimSpace(g.duckDNSDomainEntry.Text),
		DuckDNSToken:  strings.TrimSpace(g.duckDNSTokenEntry.Text),
	}

	// Validierung
	if config.Enabled {
		if config.DuckDNSDomain == "" {
			logger.Error("DuckDNS Domain ist leer!")
			dialog.ShowError(fmt.Errorf("bitte DuckDNS Domain eingeben"), g.window)
			return
		}
		if config.DuckDNSToken == "" {
			logger.Error("DuckDNS Token ist leer!")
			dialog.ShowError(fmt.Errorf("bitte DuckDNS Token eingeben"), g.window)
			return
		}

		// Entferne .duckdns.org falls eingegeben
		config.DuckDNSDomain = strings.TrimSuffix(config.DuckDNSDomain, ".duckdns.org")
		g.duckDNSDomainEntry.SetText(config.DuckDNSDomain)
	}

	// Speichern
	if err := saveExternalConfig(config); err != nil {
		logger.Error(fmt.Sprintf("Fehler beim Speichern: %v", err))
		dialog.ShowError(err, g.window)
		return
	}

	logger.Info("✅ Externe Freigabe Konfiguration gespeichert")

	// Status aktualisieren
	if config.Enabled {
		fullDomain := config.DuckDNSDomain + ".duckdns.org"
		g.externalStatusLabel.SetText(fmt.Sprintf("Status: Konfiguriert für https://%s\n⚠️ Server neu starten um zu aktivieren!", fullDomain))
	} else {
		g.externalStatusLabel.SetText("Status: Deaktiviert")
	}

	// Info Dialog
	if serverRunning {
		dialog.ShowInformation("Neustart erforderlich",
			"Die Konfiguration wurde gespeichert.\n\n"+
				"Bitte stoppen Sie den Server und starten Sie ihn neu,\n"+
				"damit die Änderungen wirksam werden.",
			g.window)
	} else {
		dialog.ShowInformation("Gespeichert",
			"Die Konfiguration wurde erfolgreich gespeichert.\n\n"+
				"Beim nächsten Server-Start wird die neue Konfiguration verwendet.",
			g.window)
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

	password := g.passwordEntry.Text

	serverPort = 7443
	serverPassword = password

	logger.Info(fmt.Sprintf("Server-Konfiguration: Port=7443, Passwort-Länge=%d Zeichen", len(password)))

	// Lade externe Freigabe Konfiguration
	extConfig := loadExternalConfig()
	externalEnabled = extConfig.Enabled
	duckDNSDomain = extConfig.DuckDNSDomain
	duckDNSToken = extConfig.DuckDNSToken

	// Datenbank initialisieren
	logger.Info("Initialisiere Datenbank...")
	if err := initDatabase(); err != nil {
		logger.Error(fmt.Sprintf("Datenbank-Initialisierung fehlgeschlagen: %v", err))
		g.addLog(fmt.Sprintf("Fehler bei Datenbank: %v", err))
		dialog.ShowError(fmt.Errorf("datenbankfehler: %v", err), g.window)
		return
	}
	logger.Info("Datenbank erfolgreich initialisiert")

	// Speichere Passwort in Datenbank
	if err := setServerSetting("server_password", password); err != nil {
		logger.Warning(fmt.Sprintf("Konnte Passwort nicht speichern: %v", err))
	} else {
		logger.Info("Passwort in Datenbank gespeichert")
	}

	// Initialize WebSocket hub
	logger.Info("Initialisiere WebSocket Hub...")
	hub = newHub()
	go hub.run()
	logger.Info("WebSocket Hub gestartet")

	// Server starten
	logger.Info("Konfiguriere Gin-Router...")
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Recovery())

	// Custom Logger Middleware verwenden
	router.Use(GinLoggerMiddleware())
	logger.Info("Custom Logger Middleware aktiviert")

	// HTTP→HTTPS Redirect Middleware (nur wenn externe Freigabe aktiv)
	router.Use(HTTPSRedirectMiddleware())
	if externalEnabled {
		logger.Info("HTTP→HTTPS Redirect Middleware aktiviert")
	}

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

	// Prüfe ob externe Freigabe aktiviert ist
	if externalEnabled && duckDNSDomain != "" && duckDNSToken != "" {
		logger.Info("🌐 Externe Freigabe aktiviert - starte HTTPS-Modus...")

		// Erst DuckDNS IP aktualisieren (damit Router dann richtigen DNS hat)
		logger.Info("Aktualisiere DuckDNS IP...")
		if err := updateDuckDNS(duckDNSDomain, duckDNSToken, "", logger); err != nil {
			logger.Warning(fmt.Sprintf("DuckDNS Update fehlgeschlagen: %v", err))
		}

		// UPnP Port-Forwarding aktivieren
		externalIP, err := setupUPnP(logger)
		if err != nil {
			logger.Error(fmt.Sprintf("UPnP-Fehler: %v", err))
			g.addLog(fmt.Sprintf("UPnP-Fehler: %v", err))
			dialog.ShowError(fmt.Errorf("upnp fehler: %v", err), g.window)
			return
		}

		if externalIP == "auto" {
			logger.Info("✅ UPnP Port 7443 erfolgreich geöffnet - DuckDNS ermittelt externe IP")
		} else {
			logger.Info(fmt.Sprintf("✅ UPnP erfolgreich - Externe IP: %s", externalIP))
		}

		// DuckDNS Updater starten (regelmäßige Updates alle 5 Min)
		startDuckDNSUpdater(duckDNSDomain, duckDNSToken, externalIP, logger)

		// Server-Start komplett asynchron (damit GUI nicht blockiert)
		serverRunning = true
		g.statusLabel.SetText("Server startet... (Zertifikat wird geladen)")
		g.startButton.SetText("Server Stoppen")
		g.passwordEntry.Disable()

		logger.Info("Lade oder erstelle Let's Encrypt Zertifikat...")
		g.addLog("🔐 Prüfe Let's Encrypt Zertifikat...")
		g.addLog("⏳ Dies kann 1-2 Minuten dauern...")

		go func() {
			// Versuche bestehendes Zertifikat zu laden
			cert, err := loadExistingCertificate(duckDNSDomain, logger)
			if err != nil {
				// Kein Zertifikat vorhanden, erstelle neues via DNS-01
				logger.Info("Kein bestehendes Zertifikat gefunden, erstelle neues...")
				g.addLog("⏳ Erstelle neues Zertifikat (DNS-01 Challenge)...")
				g.addLog("⏳ Verwendet DuckDNS - funktioniert auch bei blockierten Ports 80/443!")
				cert, err = obtainCertificateViaDNS01(duckDNSDomain, duckDNSToken, logger)
				if err != nil {
					logger.Error(fmt.Sprintf("Zertifikat-Fehler: %v", err))
					g.addLog("❌ FEHLER: Zertifikat konnte nicht erstellt werden")
					g.addLog("")

					// Analysiere den Fehler
					errMsg := err.Error()
					if strings.Contains(errMsg, "i/o timeout") || strings.Contains(errMsg, "time limit exceeded") {
						g.addLog("🔥 PROBLEM: DNS-Timeout!")
						g.addLog("")
						g.addLog("📝 MÖGLICHE URSACHEN:")
						g.addLog("  • Router/Firewall blockiert ausgehende DNS-Anfragen (Port 53 UDP)")
						g.addLog("  • DuckDNS Nameserver nicht erreichbar")
						g.addLog("  • Internet-Verbindung instabil")
						g.addLog("")
						g.addLog("🔧 LÖSUNGEN:")
						g.addLog("  1. Router-Firewall: Port 53 UDP ausgehend freigeben")
						g.addLog("  2. Windows Firewall: Port 53 UDP ausgehend erlauben")
						g.addLog("  3. DNS in Windows auf 8.8.8.8 / 1.1.1.1 ändern")
						g.addLog("  4. VPN/Proxy temporär deaktivieren")
						g.addLog("  5. Warten und neu versuchen (DNS-Server könnte überlastet sein)")
					} else if strings.Contains(errMsg, "KO") || strings.Contains(errMsg, "Ungültiger Token") {
						g.addLog("🔥 PROBLEM: DuckDNS Authentifizierung fehlgeschlagen!")
						g.addLog("")
						g.addLog("📝 LÖSUNGEN:")
						g.addLog("  1. DuckDNS Token auf duckdns.org kopieren")
						g.addLog("  2. Domain existiert und ist aktiv prüfen")
						g.addLog("  3. Token im Tab 'Externe Freigabe' neu eingeben")
					} else {
						g.addLog("🔥 MÖGLICHE URSACHEN:")
						g.addLog("  • DuckDNS Token ist ungültig")
						g.addLog("  • Domain existiert nicht bei DuckDNS")
						g.addLog("  • DNS-Propagierung dauert zu lange")
						g.addLog("  • Netzwerk-Problem")
						g.addLog("")
						g.addLog("📝 LÖSUNG:")
						g.addLog("  1. DuckDNS Token überprüfen")
						g.addLog("  2. Domain bei duckdns.org verifizieren")
						g.addLog("  3. Router/Firewall DNS-Traffic prüfen")
						g.addLog("  4. 5 Minuten warten und neu versuchen")
					}

					serverRunning = false
					g.statusLabel.SetText("Server gestoppt (Zertifikat-Fehler)")
					g.startButton.SetText("Server Starten")
					g.passwordEntry.Enable()
					return
				}
			}

			logger.Info("✓ Zertifikat bereit")
			g.addLog("✅ Zertifikat erfolgreich geladen")

			// HTTPS-Server mit TLS auf Port 7443
			httpServer = &http.Server{
				Addr:    ":7443",
				Handler: router,
				TLSConfig: &tls.Config{
					Certificates: []tls.Certificate{*cert},
				},
			}

			logger.Info("Starte HTTPS-Server auf Port 7443...")

			// Server-Status aktualisieren
			domain := duckDNSDomain
			if !strings.HasSuffix(domain, ".duckdns.org") {
				domain = domain + ".duckdns.org"
			}
			statusText := "Server läuft (HTTPS - Extern)"
			webInterface := "https://" + domain + ":7443"

			// Lokale IP für NAT Loopback Umgehung
			localIP := getLocalIP()
			localHTTPSInterface := fmt.Sprintf("https://%s:7443", localIP)

			g.statusLabel.SetText(statusText)
			g.addLog("✅ Server erfolgreich gestartet (HTTPS-Modus)!")
			g.addLog(fmt.Sprintf("🔑 Passwort: %s", serverPassword))
			g.addLog("")
			g.addLog("📡 URLs:")
			g.addLog(fmt.Sprintf("  🌐 Extern (Internet): %s", webInterface))
			g.addLog(fmt.Sprintf("  🏠 Lokal (Netzwerk): %s", localHTTPSInterface))
			g.addLog("  💻 Localhost: https://localhost:7443")
			g.addLog("")
			g.addLog("⚠️ WICHTIG für lokale Geräte:")
			g.addLog(fmt.Sprintf("   Nutze %s (nicht DuckDNS URL!)", localHTTPSInterface))
			g.addLog("   Router unterstützt kein NAT Loopback")
			g.addLog("   DuckDNS URL funktioniert nur von extern")

			logger.Info("🚀 Server erfolgreich gestartet (HTTPS)!")
			logger.Info(fmt.Sprintf("🌐 Extern verfügbar: %s", webInterface))
			logger.Info(fmt.Sprintf("🏠 Lokal verfügbar: %s", localHTTPSInterface))

			// HTTPS Server starten
			if err := httpServer.ListenAndServeTLS("", ""); err != nil && err != http.ErrServerClosed {
				logger.Error(fmt.Sprintf("HTTPS-Server Fehler: %v", err))
			}
		}()
		g.startTime = time.Now()

	} else {
		// Normaler HTTP-Modus (lokal) - auch auf Port 7443
		logger.Info("🏠 Lokaler Modus - starte HTTP-Server...")

		httpServer = &http.Server{
			Addr:    ":7443",
			Handler: router,
		}

		go func() {
			logger.Info("Starte HTTP-Server auf Port 7443...")
			if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
				logger.Error(fmt.Sprintf("HTTP-Server Fehler: %v", err))
			}
		}()

		serverRunning = true
		g.startTime = time.Now()

		statusText := "Server läuft auf Port 7443 (HTTP - Lokal)"
		webInterface := "http://localhost:7443"

		g.statusLabel.SetText(statusText)
		g.startButton.SetText("Server Stoppen")
		g.passwordEntry.Disable()

		g.addLog("Server erfolgreich gestartet!")
		g.addLog(fmt.Sprintf("Passwort: %s", serverPassword))
		g.addLog(fmt.Sprintf("Web-Interface: %s", webInterface))

		// Lokale IP-Adressen für mobile Verbindungen anzeigen
		g.addLog("Lokale IP-Adressen für mobile Geräte:")
		g.addLog(fmt.Sprintf("  - Desktop: %s", webInterface))

		// Sammle lokale IP-Adressen
		interfaces, err := net.Interfaces()
		if err == nil {
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

					if ip != nil && ip.To4() != nil {
						g.addLog(fmt.Sprintf("  - Mobile: http://%s:7443", ip.String()))
					}
				}
			}
		}

		logger.Info("🚀 Server erfolgreich gestartet!")
		logger.Info(fmt.Sprintf("🔑 Login-Passwort: %s", serverPassword))
		logger.Info("🌐 Web-Interface verfügbar: http://localhost:7443")
	}

	g.refreshIPAddresses()
	logger.Info("IP-Adressen aktualisiert - Server bereit für Verbindungen")
}

func (g *ServerGUI) stopServer() {
	logger.Info("Server-Stopp angefordert...")

	// DuckDNS Updater stoppen
	if externalEnabled {
		logger.Info("Stoppe DuckDNS Updater...")
		stopDuckDNSUpdater()
	}

	// Haupt-HTTP/HTTPS-Server stoppen
	if httpServer != nil {
		logger.Info("Beende HTTP/HTTPS-Server...")
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		if err := httpServer.Shutdown(ctx); err != nil {
			logger.Error(fmt.Sprintf("Fehler beim Stoppen des Servers: %v", err))
			g.addLog(fmt.Sprintf("Fehler beim Stoppen: %v", err))
		} else {
			logger.Info("Server erfolgreich gestoppt")
		}
		httpServer = nil
	}

	// UPnP Port-Forwarding entfernen
	if externalEnabled && upnpActive {
		logger.Info("Entferne UPnP Port-Forwarding...")
		if err := removeUPnP(logger); err != nil {
			logger.Warning(fmt.Sprintf("UPnP Cleanup Fehler: %v", err))
		}
	}

	serverRunning = false
	externalEnabled = false

	g.statusLabel.SetText("Server gestoppt")
	g.startButton.SetText("Server Starten")
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

	url := "http://localhost:7443"
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

func (g *ServerGUI) openSelectedURL() {
	if !serverRunning {
		logger.Warning("Versuch Web-Interface zu öffnen, aber Server läuft nicht")
		dialog.ShowInformation("Fehler", "Server muss zuerst gestartet werden!", g.window)
		return
	}

	selectedURL := g.urlSelect.Selected
	if selectedURL == "" || selectedURL == "Server nicht gestartet" {
		dialog.ShowInformation("Keine URL", "Bitte wähle eine URL aus der Liste!", g.window)
		return
	}

	// Extrahiere URL aus dem formatierten String
	// Format: "🌐 EXTERN (außerhalb): https://..." oder "🏠 LOKAL (IP): https://..."
	url := selectedURL

	// Entferne Prefixes
	url = strings.TrimPrefix(url, "🌐 EXTERN (außerhalb): ")
	url = strings.TrimPrefix(url, "💻 LOCALHOST: ")

	// Extrahiere URL nach letztem ": " (für lokale IPs)
	if strings.Contains(url, "): ") {
		parts := strings.Split(url, "): ")
		if len(parts) >= 2 {
			url = parts[len(parts)-1]
		}
	}

	logger.Info(fmt.Sprintf("Öffne ausgewählte URL: %s", url))

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
		logger.Info("🌐 URL erfolgreich im Browser geöffnet")
		g.addLog(fmt.Sprintf("URL geöffnet: %s", url))
	}
}

func (g *ServerGUI) refreshIPAddresses() {
	// Entferne übermäßiges Debug-Logging
	ipAddresses = []string{}

	// Prüfe ob externe Freigabe aktiv ist
	if externalEnabled && duckDNSDomain != "" {
		// Externe HTTPS URL als erstes anzeigen (nur von außerhalb erreichbar!)
		externalURL := fmt.Sprintf("https://%s.duckdns.org:7443", strings.TrimSuffix(duckDNSDomain, ".duckdns.org"))
		ipAddresses = append(ipAddresses, fmt.Sprintf("🌐 EXTERN (außerhalb): %s", externalURL))
	}

	// Lokale URLs - HTTPS wenn extern aktiv, sonst HTTP
	if externalEnabled {
		// HTTPS localhost (selbstsigniertes Zertifikat-Warnung!)
		ipAddresses = append(ipAddresses, "💻 LOCALHOST: https://localhost:7443")
	} else {
		ipAddresses = append(ipAddresses, "http://localhost:7443")
	}

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
				// HTTPS wenn extern aktiv (NAT Loopback Umgehung), sonst HTTP
				protocol := "http"
				emoji := "🏠"
				if externalEnabled {
					protocol = "https"
					emoji = "🏠"
				}
				url := fmt.Sprintf("%s LOKAL (%s): %s://%s:7443", emoji, ip.String(), protocol, ip.String())
				ipAddresses = append(ipAddresses, url)
				interfaceCount++
			}
		}
	}

	// URL-Select Dropdown aktualisieren
	if len(ipAddresses) > 0 {
		// Merke aktuelle Auswahl
		currentSelection := g.urlSelect.Selected

		g.urlSelect.Options = ipAddresses

		// Versuche die aktuelle Auswahl beizubehalten
		selectionFound := false
		for _, url := range ipAddresses {
			if url == currentSelection {
				g.urlSelect.SetSelected(currentSelection)
				selectionFound = true
				break
			}
		}

		// Falls alte Auswahl nicht mehr verfügbar: Wähle erste URL (extern oder localhost)
		if !selectionFound || currentSelection == "" || currentSelection == "Server nicht gestartet" {
			g.urlSelect.SetSelected(ipAddresses[0])
		}

		g.addLog("IP-Adressen aktualisiert")
		logger.Info(fmt.Sprintf("IP-Adressen aktualisiert - %d URLs verfügbar", len(ipAddresses)))
	} else {
		g.urlSelect.Options = []string{"Keine URLs verfügbar"}
		g.urlSelect.SetSelected("Keine URLs verfügbar")
		g.addLog("Keine IP-Adressen gefunden")
		logger.Warning("Keine verfügbaren URLs gefunden")
	}

	g.urlSelect.Refresh()
}

func (g *ServerGUI) addLog(message string) {
	timestamp := time.Now().Format("15:04:05")
	logEntry := fmt.Sprintf("[%s] %s", timestamp, message)

	g.logEntries = append(g.logEntries, logEntry)

	// Begrenze die Log-Größe (letzte 1000 Zeilen behalten)
	if len(g.logEntries) > 1000 {
		g.logEntries = g.logEntries[len(g.logEntries)-1000:]
	}

	g.logList.Refresh()

	// Auto-Scroll nach unten - scrolle zum letzten Element
	if g.autoScrollLog && len(g.logEntries) > 0 {
		lastIndex := len(g.logEntries) - 1
		go func() {
			time.Sleep(10 * time.Millisecond)
			g.logList.ScrollTo(lastIndex)
		}()
	}
}

func (g *ServerGUI) addLogWithLevel(level string, message string) {
	// Sicherheitscheck
	if g == nil || g.logList == nil {
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

	logEntry := fmt.Sprintf("[%s] %s [%s] %s", timestamp, levelColor, level, message)

	g.logEntries = append(g.logEntries, logEntry)

	// Begrenze die Log-Größe (letzte 1000 Zeilen behalten)
	if len(g.logEntries) > 1000 {
		g.logEntries = g.logEntries[len(g.logEntries)-1000:]
	}

	g.logList.Refresh()

	// Auto-Scroll nach unten - scrolle zum letzten Element
	if g.autoScrollLog && len(g.logEntries) > 0 {
		lastIndex := len(g.logEntries) - 1
		go func() {
			time.Sleep(10 * time.Millisecond)
			g.logList.ScrollTo(lastIndex)
		}()
	}
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

	// Initialize WebSocket hub
	hub = newHub()
	go hub.run()
	logText.SetText(logText.Text + "WebSocket hub initialized\n")

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

	// Lokale IP-Adressen für mobile Verbindungen anzeigen
	localIPs := getLocalIPs()
	for _, ip := range localIPs {
		if !ip.IsLoopback() && ip.To4() != nil {
			mobileURL := fmt.Sprintf("http://%s:%d", ip.String(), serverPort)
			logText.SetText(logText.Text + fmt.Sprintf("Mobile: %s\n", mobileURL))
		}
	}

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
	if err := db.AutoMigrate(&Book{}, &Wishlist{}, &Quote{}, &Genre{}, &Publisher{}, &ReadingGoal{}, &ProgressHistory{}, &ServerSettings{}); err != nil {
		if logger != nil {
			logger.Error(fmt.Sprintf("Datenbank-Migration fehlgeschlagen: %v", err))
		}
		return err
	}

	// Explizit ISBN-Spalten hinzufügen falls sie fehlen (für Updates von alten Versionen)
	if db.Migrator().HasTable(&Book{}) {
		if !db.Migrator().HasColumn(&Book{}, "isbn") {
			if logger != nil {
				logger.Info("📚 Füge ISBN-Spalte zu Books-Tabelle hinzu...")
			}
			if err := db.Migrator().AddColumn(&Book{}, "isbn"); err != nil {
				if logger != nil {
					logger.Error(fmt.Sprintf("Fehler beim Hinzufügen der ISBN-Spalte zu Books: %v", err))
				}
			}
		}
	}

	if db.Migrator().HasTable(&Wishlist{}) {
		if !db.Migrator().HasColumn(&Wishlist{}, "isbn") {
			if logger != nil {
				logger.Info("📚 Füge ISBN-Spalte zu Wishlist-Tabelle hinzu...")
			}
			if err := db.Migrator().AddColumn(&Wishlist{}, "isbn"); err != nil {
				if logger != nil {
					logger.Error(fmt.Sprintf("Fehler beim Hinzufügen der ISBN-Spalte zu Wishlist: %v", err))
				}
			}
		}
	}

	if logger != nil {
		logger.Info("✅ Datenbank erfolgreich initialisiert und migriert")
	}

	return nil
}

// Server Settings Functions
func getServerSetting(key string, defaultValue string) string {
	var setting ServerSettings
	if err := db.Where("key = ?", key).First(&setting).Error; err != nil {
		// Setting doesn't exist, return default
		return defaultValue
	}
	return setting.Value
}

func setServerSetting(key string, value string) error {
	var setting ServerSettings
	result := db.Where("key = ?", key).First(&setting)

	if result.Error != nil {
		// Setting doesn't exist, create it
		setting = ServerSettings{
			Key:   key,
			Value: value,
		}
		return db.Create(&setting).Error
	}

	// Setting exists, update it
	setting.Value = value
	return db.Save(&setting).Error
}

// ISBN Book Data Structs
type ISBNBookData struct {
	Title         string `json:"title"`
	Author        string `json:"author"`
	Genre         string `json:"genre"`
	Publisher     string `json:"publisher"`
	PublishDate   string `json:"publish_date"`
	Pages         int    `json:"pages"`
	CoverImageURL string `json:"cover_image_url"`
	CoverPath     string `json:"cover_path"` // Lokaler Pfad nach Download
}

// Google Books API Response Structs
type GoogleBooksResponse struct {
	Items []GoogleBooksItem `json:"items"`
}

type GoogleBooksItem struct {
	VolumeInfo GoogleBooksVolumeInfo `json:"volumeInfo"`
}

type GoogleBooksVolumeInfo struct {
	Title               string                  `json:"title"`
	Authors             []string                `json:"authors"`
	Publisher           string                  `json:"publisher"`
	PublishedDate       string                  `json:"publishedDate"`
	PageCount           int                     `json:"pageCount"`
	Categories          []string                `json:"categories"`
	ImageLinks          GoogleBooksImageLinks   `json:"imageLinks"`
	IndustryIdentifiers []GoogleBooksIdentifier `json:"industryIdentifiers"`
}

type GoogleBooksImageLinks struct {
	SmallThumbnail string `json:"smallThumbnail"`
	Thumbnail      string `json:"thumbnail"`
}

type GoogleBooksIdentifier struct {
	Type       string `json:"type"`
	Identifier string `json:"identifier"`
}

// Search book by ISBN using Open Library API
func searchISBN(c *gin.Context) {
	isbn := strings.ReplaceAll(c.Param("isbn"), "-", "")
	isbn = strings.TrimSpace(isbn)

	if isbn == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "ISBN ist erforderlich"})
		return
	}

	// Try Google Books API
	bookData, err := fetchFromGoogleBooks(isbn)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error":   "ISBN nicht gefunden",
			"message": "Die eingegebene ISBN konnte in der Datenbank nicht gefunden werden. Bitte überprüfen Sie die ISBN oder geben Sie die Daten manuell ein.",
			"isbn":    isbn,
		})
		return
	}

	c.JSON(http.StatusOK, bookData)
}

func fetchFromGoogleBooks(isbn string) (*ISBNBookData, error) {
	// Google Books API endpoint
	url := fmt.Sprintf("https://www.googleapis.com/books/v1/volumes?q=isbn:%s", isbn)

	resp, err := http.Get(url)
	if err != nil {
		return nil, fmt.Errorf("API-Anfrage fehlgeschlagen: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("buch nicht gefunden (Status: %d)", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("fehler beim Lesen der Antwort: %v", err)
	}

	var gbResp GoogleBooksResponse
	if err := json.Unmarshal(body, &gbResp); err != nil {
		return nil, fmt.Errorf("fehler beim Parsen der Antwort: %v", err)
	}

	// Check if we got results
	if len(gbResp.Items) == 0 {
		return nil, fmt.Errorf("keine Ergebnisse gefunden")
	}

	// Get first result
	volumeInfo := gbResp.Items[0].VolumeInfo

	// Build book data
	bookData := &ISBNBookData{
		Title: volumeInfo.Title,
		Pages: volumeInfo.PageCount,
	}

	// Get author (first author)
	if len(volumeInfo.Authors) > 0 {
		bookData.Author = volumeInfo.Authors[0]
	}

	// Get publisher
	if volumeInfo.Publisher != "" {
		bookData.Publisher = volumeInfo.Publisher
	}

	// Parse and format publish date
	if volumeInfo.PublishedDate != "" {
		bookData.PublishDate = parsePublishDate(volumeInfo.PublishedDate)
	}

	// Get genre from categories (first category as genre)
	if len(volumeInfo.Categories) > 0 {
		bookData.Genre = volumeInfo.Categories[0]
	}

	// Get cover image URL from Google Books (use thumbnail or smallThumbnail)
	// Note: Some Google Books covers redirect to "image not available" - we can't easily check this
	// without downloading, so we'll just provide the URL if available
	if volumeInfo.ImageLinks.Thumbnail != "" {
		coverURL := volumeInfo.ImageLinks.Thumbnail
		// Don't modify zoom parameter - use original URL
		bookData.CoverImageURL = coverURL
	} else if volumeInfo.ImageLinks.SmallThumbnail != "" {
		bookData.CoverImageURL = volumeInfo.ImageLinks.SmallThumbnail
	}

	return bookData, nil
}

// Parse various date formats from Open Library
func parsePublishDate(dateStr string) string {
	dateStr = strings.TrimSpace(dateStr)

	// Try to parse different formats
	formats := []string{
		"January 2, 2006", // "January 1, 2020"
		"Jan 2, 2006",     // "Jan 1, 2020"
		"2006-01-02",      // "2020-01-01"
		"2006",            // "2020"
		"January 2006",    // "January 2020"
		"Jan 2006",        // "Jan 2020"
		"02 January 2006", // "01 January 2020"
		"2 January 2006",  // "1 January 2020"
	}

	for _, format := range formats {
		if t, err := time.Parse(format, dateStr); err == nil {
			return t.Format("2006-01-02") // Return as YYYY-MM-DD
		}
	}

	// If only year is given
	if len(dateStr) == 4 {
		if _, err := strconv.Atoi(dateStr); err == nil {
			return dateStr + "-01-01"
		}
	}

	// Return original if can't parse
	return dateStr
}

// Download cover image and save to uploads folder
func downloadAndSaveCover(coverURL, isbn string) (string, error) {
	// Create uploads directory if not exists
	uploadsDir := "./uploads/covers"
	if err := os.MkdirAll(uploadsDir, 0755); err != nil {
		return "", err
	}

	// Download image
	resp, err := http.Get(coverURL)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("failed to download cover: status %d", resp.StatusCode)
	}

	// Generate filename
	filename := fmt.Sprintf("isbn_%s_%d.jpg", isbn, time.Now().Unix())
	filepath := filepath.Join(uploadsDir, filename)

	// Create file
	out, err := os.Create(filepath)
	if err != nil {
		return "", err
	}
	defer out.Close()

	// Copy data
	_, err = io.Copy(out, resp.Body)
	if err != nil {
		return "", err
	}

	// Return only filename for database (frontend will add /uploads/covers/)
	return filename, nil
}

// Download cover from URL endpoint
func downloadCoverFromURL(c *gin.Context) {
	var request struct {
		CoverURL string `json:"cover_url" binding:"required"`
		ISBN     string `json:"isbn"`
	}

	if err := c.ShouldBindJSON(&request); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Cover URL ist erforderlich"})
		return
	}

	// Use ISBN or timestamp for filename
	identifier := request.ISBN
	if identifier == "" {
		identifier = fmt.Sprintf("%d", time.Now().Unix())
	}

	coverPath, err := downloadAndSaveCover(request.CoverURL, identifier)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Fehler beim Herunterladen des Covers: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"cover_path": coverPath,
		"success":    true,
	})
}

// ============================================================================
// External Access Configuration API
// ============================================================================

// getExternalConfig gibt die aktuelle externe Konfiguration zurück
func getExternalConfig(c *gin.Context) {
	config := loadExternalConfig()

	// Gebe aktuellen Status mit zurück
	c.JSON(http.StatusOK, gin.H{
		"enabled":        config.Enabled,
		"duckdns_domain": config.DuckDNSDomain,
		"duckdns_token":  config.DuckDNSToken,
		"active":         externalEnabled && serverRunning,
		"upnp_active":    upnpActive,
	})
}

// updateExternalConfig aktualisiert die externe Konfiguration
func updateExternalConfig(c *gin.Context) {
	var config ExternalConfig

	if err := c.ShouldBindJSON(&config); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Ungültige Konfiguration"})
		return
	}

	// Validierung
	if config.Enabled {
		if config.DuckDNSDomain == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "DuckDNS Domain ist erforderlich"})
			return
		}
		if config.DuckDNSToken == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "DuckDNS Token ist erforderlich"})
			return
		}
	}

	// Speichern
	if err := saveExternalConfig(config); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Fehler beim Speichern: " + err.Error()})
		return
	}

	// Info: Server muss neu gestartet werden um Änderungen zu übernehmen
	needsRestart := serverRunning && (config.Enabled != externalEnabled ||
		config.DuckDNSDomain != duckDNSDomain ||
		config.DuckDNSToken != duckDNSToken)

	c.JSON(http.StatusOK, gin.H{
		"success":       true,
		"needs_restart": needsRestart,
		"message":       "Konfiguration gespeichert",
	})
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

	// WebSocket endpoint
	router.GET("/ws", handleWebSocket)

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
		// Public routes
		api.GET("/version", func(c *gin.Context) {
			c.JSON(200, gin.H{
				"version": AppVersion,
				"name":    AppName,
				"author":  AppAuthor,
			})
		})

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
			protected.POST("/books/:id/copy-cover", copyBookCover)
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

			protected.GET("/isbn/:isbn", searchISBN)
			protected.POST("/download-cover", downloadCoverFromURL)

			// External Access Configuration
			protected.GET("/external-config", getExternalConfig)
			protected.POST("/external-config", updateExternalConfig)
		}
	}

	// PWA-Installation Hilfe
	router.GET("/pwa-help", func(c *gin.Context) {
		helpHTML := `
<!DOCTYPE html>
<html>
<head>
    <title>PWA Installation Hilfe</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 600px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; }
        h1 { color: #333; }
        .step { margin: 15px 0; padding: 10px; background: #e8f4f8; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📱 PWA Installation Hilfe</h1>
        
        <h2>PWA-Installation</h2>
        <div class="step">
            <strong>1.</strong> Öffnen Sie die Reading Diary App in Ihrem Browser
        </div>
        <div class="step">
            <strong>2.</strong> Suchen Sie nach dem "Installieren" Button oder "Zum Startbildschirm hinzufügen"
        </div>
        <div class="step">
            <strong>3.</strong> Folgen Sie den Anweisungen Ihres Browsers
        </div>

        <h2>🔧 Browser-spezifische Anweisungen</h2>
        <div class="step">
            <strong>Chrome:</strong> Suchen Sie nach dem "Installieren" Symbol in der Adressleiste
        </div>
        <div class="step">
            <strong>Firefox:</strong> Menü → "Diese Seite installieren"
        </div>
        <div class="step">
            <strong>Safari:</strong> Teilen → "Zum Home-Bildschirm hinzufügen"
        </div>

        <p><a href="/">← Zurück zur App</a></p>
    </div>
</body>
</html>`
		c.Data(200, "text/html; charset=utf-8", []byte(helpHTML))
	})
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

	// Debug: Alle eingehenden Daten loggen (nur bei Fehlern)
	// logger.Debug(fmt.Sprintf("createBook: Empfangene Daten: %+v", book))

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

	// Automatisches Erstellen des Genres falls es nicht existiert
	if err := ensureGenreExists(book.Genre); err != nil {
		logger.Error(fmt.Sprintf("createBook: Fehler beim Erstellen des Genres: %v", err))
		c.JSON(500, gin.H{"error": fmt.Sprintf("Fehler beim Verarbeiten des Genres: %v", err)})
		return
	}

	if book.PublishDate == "" {
		logger.Warning(fmt.Sprintf("createBook: Erscheinungsdatum fehlt: '%s'", book.PublishDate))
		c.JSON(400, gin.H{"error": "Erscheinungsdatum ist erforderlich"})
		return
	}

	// logger.Debug("createBook: Alle Validierungen bestanden, erstelle Buch")

	if err := db.Create(&book).Error; err != nil {
		logger.Error(fmt.Sprintf("createBook: Datenbankfehler: %v", err))
		c.JSON(500, gin.H{"error": fmt.Sprintf("Konnte Buch nicht erstellen: %v", err)})
		return
	}

	logger.Info(fmt.Sprintf("createBook: Neues Buch erstellt - ID: %d, Titel: %s", book.ID, book.Title))

	// Broadcast WebSocket event
	broadcastEvent("book_created", book)
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
	// logger.Debug(fmt.Sprintf("updateBook: Empfangene Daten: %+v", requestData))

	// Erstelle ein neues Book-Objekt basierend auf dem bestehenden Buch
	updatedBook := existingBook // Kopiere alle bestehenden Werte

	// Manuell die Felder aktualisieren, die im Request enthalten sind
	if title, ok := requestData["title"].(string); ok {
		updatedBook.Title = title
	}
	if author, ok := requestData["author"].(string); ok {
		updatedBook.Author = author
	}
	if isbn, ok := requestData["isbn"].(string); ok {
		updatedBook.ISBN = isbn
	}
	if genre, ok := requestData["genre"].(string); ok {
		updatedBook.Genre = genre
		// Automatisches Erstellen des Genres falls es nicht existiert
		if genre != "" {
			if err := ensureGenreExists(genre); err != nil {
				logger.Error(fmt.Sprintf("updateBook: Fehler beim Erstellen des Genres: %v", err))
				c.JSON(500, gin.H{"error": fmt.Sprintf("Fehler beim Verarbeiten des Genres: %v", err)})
				return
			}
		}
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

	// logger.Debug(fmt.Sprintf("updateBook: Verarbeitete Buchdaten: %+v", updatedBook))

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

	// Broadcast WebSocket event
	broadcastEvent("book_updated", updatedBook)

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

	// Broadcast WebSocket event
	broadcastEvent("book_deleted", gin.H{"id": book.ID})

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

	// Broadcast WebSocket event
	broadcastEvent("book_updated", book)

	c.JSON(200, gin.H{
		"message":     "Cover erfolgreich hochgeladen",
		"cover_image": filename,
		"book":        book,
	})
}

func copyBookCover(c *gin.Context) {
	id := c.Param("id")

	// Prüfen ob das Buch existiert
	var book Book
	if err := db.First(&book, id).Error; err != nil {
		c.JSON(404, gin.H{"error": "Buch nicht gefunden"})
		return
	}

	// Cover-Quellpfad aus Request lesen
	var request struct {
		SourceCover string `json:"source_cover" binding:"required"`
	}
	if err := c.ShouldBindJSON(&request); err != nil {
		c.JSON(400, gin.H{"error": "Quell-Cover fehlt"})
		return
	}

	uploadDir := filepath.Join("uploads", "covers")
	sourcePath := filepath.Join(uploadDir, request.SourceCover)

	// Prüfen ob Quell-Cover existiert
	if _, err := os.Stat(sourcePath); os.IsNotExist(err) {
		c.JSON(404, gin.H{"error": "Quell-Cover nicht gefunden"})
		return
	}

	// Quell-Datei öffnen
	sourceFile, err := os.Open(sourcePath)
	if err != nil {
		logger.Error(fmt.Sprintf("Konnte Quell-Cover nicht öffnen: %v", err))
		c.JSON(500, gin.H{"error": "Konnte Cover nicht kopieren"})
		return
	}
	defer sourceFile.Close()

	// Neuen Dateinamen für Buch generieren
	ext := filepath.Ext(request.SourceCover)
	filename := fmt.Sprintf("book_%s_%d%s", id, time.Now().Unix(), ext)
	destPath := filepath.Join(uploadDir, filename)

	// Ziel-Datei erstellen
	destFile, err := os.Create(destPath)
	if err != nil {
		logger.Error(fmt.Sprintf("Konnte Ziel-Cover nicht erstellen: %v", err))
		c.JSON(500, gin.H{"error": "Konnte Cover nicht kopieren"})
		return
	}
	defer destFile.Close()

	// Cover kopieren
	if _, err := io.Copy(destFile, sourceFile); err != nil {
		logger.Error(fmt.Sprintf("Konnte Cover nicht kopieren: %v", err))
		os.Remove(destPath) // Aufräumen
		c.JSON(500, gin.H{"error": "Konnte Cover nicht kopieren"})
		return
	}

	// Altes Cover vom Buch löschen, falls vorhanden
	if book.CoverImage != "" {
		oldCoverPath := filepath.Join(uploadDir, book.CoverImage)
		if _, err := os.Stat(oldCoverPath); err == nil {
			if err := os.Remove(oldCoverPath); err != nil {
				logger.Error(fmt.Sprintf("Konnte altes Buch-Cover nicht löschen: %v", err))
			}
		}
	}

	// Buch in der Datenbank aktualisieren
	book.CoverImage = filename
	if err := db.Save(&book).Error; err != nil {
		logger.Error(fmt.Sprintf("Konnte Buch-Cover in Datenbank nicht aktualisieren: %v", err))
		os.Remove(destPath) // Aufräumen
		c.JSON(500, gin.H{"error": "Konnte Cover-Referenz nicht speichern"})
		return
	}

	logger.Info(fmt.Sprintf("Cover für Buch ID %s erfolgreich kopiert von %s", id, request.SourceCover))

	// Broadcast WebSocket event
	broadcastEvent("book_updated", book)

	c.JSON(200, gin.H{
		"message":     "Cover erfolgreich kopiert",
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

	// Broadcast WebSocket event
	broadcastEvent("wishlist_updated", wishlistItem)

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

	// Automatisches Erstellen des Genres falls es nicht existiert (falls Genre angegeben)
	if item.Genre != "" {
		if err := ensureGenreExists(item.Genre); err != nil {
			logger.Error(fmt.Sprintf("createWishlistItem: Fehler beim Erstellen des Genres: %v", err))
			c.JSON(500, gin.H{"error": fmt.Sprintf("Fehler beim Verarbeiten des Genres: %v", err)})
			return
		}
	}

	if err := db.Create(&item).Error; err != nil {
		c.JSON(500, gin.H{"error": "Datenbankfehler"})
		return
	}

	broadcastEvent("wishlist_created", item)
	c.JSON(201, item)
}

func deleteWishlistItem(c *gin.Context) {
	id := c.Param("id")

	// Erst den Wunschlisten-Eintrag holen, um Cover-Pfad zu bekommen
	var wishlistItem Wishlist
	if err := db.First(&wishlistItem, id).Error; err != nil {
		c.JSON(404, gin.H{"error": "Wunschliste-Eintrag nicht gefunden"})
		return
	}

	// Cover-Datei löschen, falls vorhanden
	if wishlistItem.CoverImage != "" {
		coverPath := filepath.Join("uploads", "covers", wishlistItem.CoverImage)
		if _, err := os.Stat(coverPath); err == nil {
			if err := os.Remove(coverPath); err != nil {
				logger.Error(fmt.Sprintf("Konnte Wunschlisten-Cover-Datei nicht löschen: %v", err))
			} else {
				logger.Info(fmt.Sprintf("Wunschlisten-Cover-Datei gelöscht: %s", coverPath))
			}
		}
	}

	// Eintrag aus der Datenbank löschen
	if err := db.Delete(&Wishlist{}, id).Error; err != nil {
		c.JSON(500, gin.H{"error": "Konnte Eintrag nicht löschen"})
		return
	}

	broadcastEvent("wishlist_deleted", gin.H{"id": id})
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

	// Broadcast book created event
	broadcastEvent("book_created", book)

	// Lösche Wunschlisteneintrag
	db.Delete(&wishlistItem)

	// Broadcast wishlist deleted event
	broadcastEvent("wishlist_deleted", gin.H{"id": wishlistItem.ID})

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

	broadcastEvent("quote_created", quote)
	c.JSON(201, quote)
}

func deleteQuote(c *gin.Context) {
	id := c.Param("id")
	if err := db.Delete(&Quote{}, id).Error; err != nil {
		c.JSON(500, gin.H{"error": "Konnte Zitat nicht löschen"})
		return
	}

	broadcastEvent("quote_deleted", gin.H{"id": id})
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

// Hilfsfunktion zum Erstellen eines Genres falls es nicht existiert
func ensureGenreExists(genreName string) error {
	if genreName == "" {
		return fmt.Errorf("genre-name ist leer")
	}

	// Prüfe ob Genre bereits existiert
	var existingGenre Genre
	if err := db.Where("name = ?", genreName).First(&existingGenre).Error; err == nil {
		// Genre existiert bereits
		return nil
	}

	// Erstelle neues Genre
	newGenre := Genre{Name: genreName}
	if err := db.Create(&newGenre).Error; err != nil {
		logger.Error(fmt.Sprintf("Fehler beim Erstellen des Genres '%s': %v", genreName, err))
		return err
	}

	logger.Info(fmt.Sprintf("Neues Genre automatisch erstellt: %s", genreName))
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
	if isbn, ok := requestData["isbn"].(string); ok {
		updatedItem.ISBN = isbn
	}
	if coverImage, ok := requestData["cover_image"].(string); ok {
		updatedItem.CoverImage = coverImage
	}
	if genre, ok := requestData["genre"].(string); ok {
		updatedItem.Genre = genre
		// Automatisches Erstellen des Genres falls es nicht existiert
		if genre != "" {
			if err := ensureGenreExists(genre); err != nil {
				logger.Error(fmt.Sprintf("updateWishlistItem: Fehler beim Erstellen des Genres: %v", err))
				c.JSON(500, gin.H{"error": fmt.Sprintf("Fehler beim Verarbeiten des Genres: %v", err)})
				return
			}
		}
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
	broadcastEvent("wishlist_updated", updatedItem)
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

	// Broadcast WebSocket event
	broadcastEvent("book_updated", book)

	c.JSON(200, gin.H{"message": "Status erfolgreich geändert", "book": book})
}

// getLocalIPs gibt alle lokalen IP-Adressen zurück
func getLocalIPs() []net.IP {
	var ips []net.IP

	interfaces, err := net.Interfaces()
	if err != nil {
		return ips
	}

	for _, iface := range interfaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}

		addresses, err := iface.Addrs()
		if err != nil {
			continue
		}

		for _, addr := range addresses {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			}

			if ip != nil && !ip.IsLoopback() {
				ips = append(ips, ip)
			}
		}
	}

	return ips
}

// Ende der Datei

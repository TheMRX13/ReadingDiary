using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.NetworkInformation;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;

namespace ServerGui
{
    public partial class MainWindow : Window, INotifyPropertyChanged
    {
        private Process? serverProcess;
        private readonly DispatcherTimer updateTimer;
        private DateTime startTime;
        private readonly StringBuilder logMessages = new();
        
        // Einstellungen
        private int serverPort = 7443;
        private string serverPassword = "admin123";
        
        // Properties für Data Binding
        private bool _isServerRunning;
        public bool IsServerRunning
        {
            get => _isServerRunning;
            set
            {
                _isServerRunning = value;
                OnPropertyChanged(nameof(IsServerRunning));
                OnPropertyChanged(nameof(StartButtonText));
                OnPropertyChanged(nameof(CanChangeSettings));
            }
        }
        
        public string StartButtonText => IsServerRunning ? "Server Stoppen" : "Server Starten";
        public bool CanChangeSettings => !IsServerRunning;
        
        private string _statusText = "Server gestoppt";
        public string StatusText
        {
            get => _statusText;
            set
            {
                _statusText = value;
                OnPropertyChanged(nameof(StatusText));
            }
        }
        
        private string _uptimeText = "00:00:00";
        public string UptimeText
        {
            get => _uptimeText;
            set
            {
                _uptimeText = value;
                OnPropertyChanged(nameof(UptimeText));
            }
        }
        
        private string _ipAddresses = "Nicht verfügbar";
        public string IpAddresses
        {
            get => _ipAddresses;
            set
            {
                _ipAddresses = value;
                OnPropertyChanged(nameof(IpAddresses));
            }
        }

        public MainWindow()
        {
            InitializeComponent();
            DataContext = this;
            
            updateTimer = new DispatcherTimer
            {
                Interval = TimeSpan.FromSeconds(1)
            };
            updateTimer.Tick += UpdateTimer_Tick;
            
            LoadSettings();
            UpdateIpAddresses();
            AddLogMessage("Server GUI gestartet - Coded by TheMRX");
            
            Closing += MainWindow_Closing;
        }
        
        private void LoadSettings()
        {
            PortTextBox.Text = serverPort.ToString();
            PasswordBox.Password = serverPassword;
        }
        
        private void SaveSettings()
        {
            if (int.TryParse(PortTextBox.Text, out int port) && port > 0 && port <= 65535)
            {
                serverPort = port;
            }
            serverPassword = PasswordBox.Password;
            UpdateIpAddresses(); // IP-Adressen mit neuem Port aktualisieren
        }

        private async void StartStopButton_Click(object sender, RoutedEventArgs e)
        {
            if (IsServerRunning)
            {
                await StopServer();
            }
            else
            {
                await StartServer();
            }
        }

        private async Task StartServer()
        {
            try
            {
                SaveSettings();
                
                var serverExePath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "ReadingDiaryServer.exe");
                if (!File.Exists(serverExePath))
                {
                    AddLogMessage("Fehler: ReadingDiaryServer.exe nicht gefunden!");
                    AddLogMessage($"Erwartet in: {serverExePath}");
                    return;
                }

                var startInfo = new ProcessStartInfo
                {
                    FileName = serverExePath,
                    Arguments = $"{serverPort} \"{serverPassword}\"",
                    WorkingDirectory = AppDomain.CurrentDomain.BaseDirectory,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                };

                serverProcess = new Process { StartInfo = startInfo };
                serverProcess.OutputDataReceived += (s, e) => {
                    if (!string.IsNullOrEmpty(e.Data))
                    {
                        Dispatcher.Invoke(() => AddLogMessage($"[SERVER] {e.Data}"));
                    }
                };
                serverProcess.ErrorDataReceived += (s, e) => {
                    if (!string.IsNullOrEmpty(e.Data))
                    {
                        Dispatcher.Invoke(() => AddLogMessage($"[ERROR] {e.Data}"));
                    }
                };

                serverProcess.Start();
                serverProcess.BeginOutputReadLine();
                serverProcess.BeginErrorReadLine();

                startTime = DateTime.Now;
                IsServerRunning = true;
                StatusText = $"Server läuft auf Port {serverPort}";
                updateTimer.Start();
                
                AddLogMessage($"Server gestartet auf Port {serverPort}");
                AddLogMessage($"Passwort: {serverPassword}");
                
                // Kurz warten und dann prüfen ob Server läuft
                await Task.Delay(2000);
                if (serverProcess?.HasExited == true)
                {
                    IsServerRunning = false;
                    StatusText = "Server gestoppt (Fehler beim Start)";
                    updateTimer.Stop();
                    AddLogMessage("Server wurde unerwartet beendet");
                }
                else
                {
                    AddLogMessage($"Web-Interface verfügbar unter: http://localhost:{serverPort}");
                    AddLogMessage("Server erfolgreich gestartet!");
                }
            }
            catch (Exception ex)
            {
                AddLogMessage($"Fehler beim Starten: {ex.Message}");
                IsServerRunning = false;
                StatusText = "Server gestoppt (Fehler)";
            }
        }

        private async Task StopServer()
        {
            try
            {
                if (serverProcess != null && !serverProcess.HasExited)
                {
                    AddLogMessage("Stoppe Server...");
                    serverProcess.Kill();
                    await Task.Run(() => serverProcess.WaitForExit(5000));
                }
                
                serverProcess?.Dispose();
                serverProcess = null;
                
                IsServerRunning = false;
                StatusText = "Server gestoppt";
                updateTimer.Stop();
                UptimeText = "00:00:00";
                
                AddLogMessage("Server erfolgreich gestoppt");
            }
            catch (Exception ex)
            {
                AddLogMessage($"Fehler beim Stoppen: {ex.Message}");
            }
        }

        private void UpdateTimer_Tick(object? sender, EventArgs e)
        {
            if (IsServerRunning && serverProcess != null && !serverProcess.HasExited)
            {
                var uptime = DateTime.Now - startTime;
                UptimeText = $"{uptime.Hours:D2}:{uptime.Minutes:D2}:{uptime.Seconds:D2}";
            }
            else if (IsServerRunning)
            {
                // Server ist unerwartet beendet worden
                IsServerRunning = false;
                StatusText = "Server gestoppt (unerwartet beendet)";
                updateTimer.Stop();
                AddLogMessage("Server wurde unerwartet beendet");
            }
        }
        
        private void UpdateIpAddresses()
        {
            try
            {
                var addresses = new StringBuilder();
                addresses.AppendLine($"http://localhost:{serverPort}");
                
                foreach (NetworkInterface ni in NetworkInterface.GetAllNetworkInterfaces())
                {
                    if (ni.OperationalStatus == OperationalStatus.Up && 
                        ni.NetworkInterfaceType != NetworkInterfaceType.Loopback)
                    {
                        foreach (UnicastIPAddressInformation ip in ni.GetIPProperties().UnicastAddresses)
                        {
                            if (ip.Address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
                            {
                                addresses.AppendLine($"http://{ip.Address}:{serverPort}");
                            }
                        }
                    }
                }
                
                if (addresses.Length > 0)
                {
                    IpAddresses = addresses.ToString().Trim();
                }
                else
                {
                    IpAddresses = "Keine Netzwerkverbindung";
                }
            }
            catch
            {
                IpAddresses = "Fehler beim Ermitteln der IP-Adressen";
            }
        }

        private void RefreshIpButton_Click(object sender, RoutedEventArgs e)
        {
            UpdateIpAddresses();
            AddLogMessage("IP-Adressen aktualisiert");
        }

        private void OpenWebInterfaceButton_Click(object sender, RoutedEventArgs e)
        {
            if (IsServerRunning)
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = $"http://localhost:{serverPort}",
                        UseShellExecute = true
                    });
                    AddLogMessage("Web-Interface geöffnet");
                }
                catch (Exception ex)
                {
                    AddLogMessage($"Fehler beim Öffnen des Web-Interface: {ex.Message}");
                }
            }
            else
            {
                AddLogMessage("Server muss erst gestartet werden!");
            }
        }

        private void ExportLogButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                var logFile = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, $"server-log-{DateTime.Now:yyyy-MM-dd-HH-mm-ss}.txt");
                File.WriteAllText(logFile, logMessages.ToString());
                AddLogMessage($"Log exportiert nach: {logFile}");
            }
            catch (Exception ex)
            {
                AddLogMessage($"Fehler beim Exportieren: {ex.Message}");
            }
        }

        private void ClearLogButton_Click(object sender, RoutedEventArgs e)
        {
            logMessages.Clear();
            LogTextBox.Clear();
            AddLogMessage("Log geleert");
        }

        private void AddLogMessage(string message)
        {
            var timestamp = DateTime.Now.ToString("HH:mm:ss");
            var logEntry = $"[{timestamp}] {message}\n";
            
            logMessages.Append(logEntry);
            LogTextBox.AppendText(logEntry);
            LogTextBox.ScrollToEnd();
        }

        private async void MainWindow_Closing(object? sender, CancelEventArgs e)
        {
            if (IsServerRunning)
            {
                var result = MessageBox.Show(
                    "Der Server läuft noch. Möchten Sie ihn vor dem Beenden stoppen?",
                    "Server läuft",
                    MessageBoxButton.YesNoCancel,
                    MessageBoxImage.Question);

                if (result == MessageBoxResult.Yes)
                {
                    e.Cancel = true;
                    await StopServer();
                    Application.Current.Shutdown();
                }
                else if (result == MessageBoxResult.Cancel)
                {
                    e.Cancel = true;
                }
            }
        }

        public event PropertyChangedEventHandler? PropertyChanged;
        protected virtual void OnPropertyChanged(string propertyName)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}
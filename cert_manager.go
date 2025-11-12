package main

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/go-acme/lego/v4/certcrypto"
	"github.com/go-acme/lego/v4/certificate"
	"github.com/go-acme/lego/v4/challenge/dns01"
	"github.com/go-acme/lego/v4/lego"
	"github.com/go-acme/lego/v4/providers/dns/duckdns"
	"github.com/go-acme/lego/v4/registration"
)

// ACMEUser implementiert registration.User für Let's Encrypt
type ACMEUser struct {
	Email        string
	Registration *registration.Resource
	key          crypto.PrivateKey
}

func (u *ACMEUser) GetEmail() string {
	return u.Email
}

func (u *ACMEUser) GetRegistration() *registration.Resource {
	return u.Registration
}

func (u *ACMEUser) GetPrivateKey() crypto.PrivateKey {
	return u.key
}

// obtainCertificateViaDNS01 holt ein Let's Encrypt Zertifikat über DNS-01 Challenge mit DuckDNS
// Dies funktioniert auch wenn Ports 80/443 blockiert sind!
func obtainCertificateViaDNS01(domain string, duckdnsToken string, logger Logger) (*tls.Certificate, error) {
	logger.Info("Starte Let's Encrypt Zertifikatsausstellung via DNS-01 (DuckDNS)...")

	// Stelle sicher, dass Domain .duckdns.org Suffix hat
	if !strings.Contains(domain, ".") {
		domain = domain + ".duckdns.org"
	}

	// Private Key generieren
	privateKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("fehler beim Generieren des Private Keys: %v", err)
	}

	// ACME User erstellen
	myUser := &ACMEUser{
		Email: "admin@" + domain,
		key:   privateKey,
	}

	// Lego Config
	config := lego.NewConfig(myUser)
	config.Certificate.KeyType = certcrypto.RSA2048

	// Let's Encrypt Production Server
	config.CADirURL = lego.LEDirectoryProduction

	// ACME Client erstellen
	client, err := lego.NewClient(config)
	if err != nil {
		return nil, fmt.Errorf("fehler beim Erstellen des ACME Clients: %v", err)
	}

	// DuckDNS DNS Provider konfigurieren
	logger.Info("Konfiguriere DNS-01 Challenge mit DuckDNS...")
	os.Setenv("DUCKDNS_TOKEN", duckdnsToken)

	provider, err := duckdns.NewDNSProvider()
	if err != nil {
		return nil, fmt.Errorf("fehler beim Erstellen des DuckDNS Providers: %v", err)
	}

	// DNS-01 Challenge mit sehr aggressiven Timeouts und mehreren DNS-Servern
	err = client.Challenge.SetDNS01Provider(provider,
		dns01.AddDNSTimeout(300*time.Second), // 5 Minuten Timeout (DuckDNS kann langsam sein)
		dns01.AddRecursiveNameservers([]string{
			"8.8.8.8:53", // Google Primary
			"8.8.4.4:53", // Google Secondary
			"1.1.1.1:53", // Cloudflare Primary
			"1.0.0.1:53", // Cloudflare Secondary
			"9.9.9.9:53", // Quad9
		}),
		dns01.DisableCompletePropagationRequirement(), // Nicht alle Nameserver müssen antworten
	)
	if err != nil {
		return nil, fmt.Errorf("fehler beim Konfigurieren von DNS-01: %v", err)
	}

	// Registrierung bei Let's Encrypt
	logger.Info("Registriere bei Let's Encrypt...")
	reg, err := client.Registration.Register(registration.RegisterOptions{TermsOfServiceAgreed: true})
	if err != nil {
		return nil, fmt.Errorf("fehler bei der Registrierung: %v", err)
	}
	myUser.Registration = reg

	logger.Info(fmt.Sprintf("Beantrage Zertifikat für %s via DNS-01...", domain))
	logger.Info("⏳ Let's Encrypt erstellt TXT-Record bei DuckDNS...")
	logger.Info("⏳ Dies kann 2-5 Minuten dauern (DNS-Propagierung)...")
	logger.Warning("Falls Timeout: Prüfe ob ausgehende DNS-Anfragen (Port 53 UDP) blockiert sind!")

	// Zertifikat anfordern
	request := certificate.ObtainRequest{
		Domains: []string{domain},
		Bundle:  true,
	}

	certificates, err := client.Certificate.Obtain(request)
	if err != nil {
		return nil, fmt.Errorf("fehler beim Beantragen des Zertifikats: %v", err)
	}

	logger.Info("✓ Zertifikat erfolgreich ausgestellt!")

	// Zertifikat speichern
	certDir := filepath.Join(".", "certs")
	os.MkdirAll(certDir, 0700)

	certFile := filepath.Join(certDir, domain+".crt")
	keyFile := filepath.Join(certDir, domain+".key")

	err = os.WriteFile(certFile, certificates.Certificate, 0600)
	if err != nil {
		return nil, fmt.Errorf("fehler beim Speichern des Zertifikats: %v", err)
	}

	err = os.WriteFile(keyFile, certificates.PrivateKey, 0600)
	if err != nil {
		return nil, fmt.Errorf("fehler beim Speichern des Private Keys: %v", err)
	}

	logger.Info(fmt.Sprintf("Zertifikat gespeichert: %s", certFile))

	// TLS Certificate laden
	cert, err := tls.X509KeyPair(certificates.Certificate, certificates.PrivateKey)
	if err != nil {
		return nil, fmt.Errorf("fehler beim Laden des TLS Zertifikats: %v", err)
	}

	return &cert, nil
}

// loadExistingCertificate versucht, ein bestehendes Zertifikat zu laden
func loadExistingCertificate(domain string, logger Logger) (*tls.Certificate, error) {
	if !strings.Contains(domain, ".") {
		domain = domain + ".duckdns.org"
	}

	certFile := filepath.Join(".", "certs", domain+".crt")
	keyFile := filepath.Join(".", "certs", domain+".key")

	// Prüfe ob Dateien existieren
	if _, err := os.Stat(certFile); os.IsNotExist(err) {
		return nil, fmt.Errorf("zertifikat nicht gefunden")
	}
	if _, err := os.Stat(keyFile); os.IsNotExist(err) {
		return nil, fmt.Errorf("private key nicht gefunden")
	}

	// Lade Zertifikat
	cert, err := tls.LoadX509KeyPair(certFile, keyFile)
	if err != nil {
		return nil, fmt.Errorf("fehler beim Laden: %v", err)
	}

	logger.Info(fmt.Sprintf("Bestehendes Zertifikat geladen: %s", certFile))
	return &cert, nil
}

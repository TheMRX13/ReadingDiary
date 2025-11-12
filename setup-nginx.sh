#!/bin/bash

# Reading Diary - Nginx + Let's Encrypt Setup Script
# Dieses Script auf dem Ubuntu Server ausführen

echo "================================================"
echo "   Reading Diary - Nginx + Let's Encrypt Setup"
echo "================================================"
echo ""

# Prüfe ob als root ausgeführt
if [ "$EUID" -ne 0 ]; then 
    echo "Bitte als root ausführen: sudo ./setup-nginx.sh"
    exit 1
fi

# Voreinstellungen
DOMAIN="readingdiary.webhop.me"
EMAIL="keller.pascal1313@pm.me"

echo "Automatische Konfiguration:"
echo "Domain: $DOMAIN"
echo "E-Mail: $EMAIL"
echo ""

echo ""
echo "[1/6] Installiere Nginx und Certbot..."
apt update
apt install -y nginx certbot python3-certbot-nginx

if [ $? -ne 0 ]; then
    echo "Fehler bei der Installation!"
    exit 1
fi

echo ""
echo "[2/6] Stoppe Nginx temporär..."
systemctl stop nginx

echo ""
echo "[3/6] Erstelle Nginx-Konfiguration (HTTP-only für Certbot)..."

# Erstelle initiale HTTP-only Config (SSL wird von Certbot hinzugefügt)
cat > /etc/nginx/sites-available/reading-diary <<EOF
# Reading Diary - Nginx Configuration
# Initial HTTP-only config - SSL wird von Certbot automatisch hinzugefügt

server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    # Logging
    access_log /var/log/nginx/reading-diary-access.log;
    error_log /var/log/nginx/reading-diary-error.log;

    # Max Upload Size
    client_max_body_size 10M;

    # Let's Encrypt ACME Challenge
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Proxy zu Reading Diary Server
    location / {
        proxy_pass http://localhost:7443;
        proxy_http_version 1.1;
        
        # WebSocket Support
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        
        # Standard Headers
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        proxy_cache_bypass \$http_upgrade;
        proxy_buffering off;
    }
}
EOF

echo "[4/6] Aktiviere Nginx-Config..."
ln -sf /etc/nginx/sites-available/reading-diary /etc/nginx/sites-enabled/

# Entferne default config
rm -f /etc/nginx/sites-enabled/default

# Teste Nginx Config
nginx -t
if [ $? -ne 0 ]; then
    echo "Fehler in der Nginx-Konfiguration!"
    exit 1
fi

echo ""
echo "[5/6] Starte Nginx..."
systemctl start nginx
systemctl enable nginx

echo ""
echo "[6/6] Hole SSL-Zertifikat von Let's Encrypt..."
echo "Dies kann einen Moment dauern..."
echo ""

certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email $EMAIL --redirect

if [ $? -ne 0 ]; then
    echo ""
    echo "Fehler beim Erstellen des SSL-Zertifikats!"
    echo ""
    echo "Mögliche Probleme:"
    echo "1. Domain zeigt nicht auf diesen Server"
    echo "2. Port 80/443 nicht erreichbar (Firewall?)"
    echo "3. Nginx läuft nicht"
    echo ""
    echo "Manuell versuchen:"
    echo "  sudo certbot --nginx -d $DOMAIN"
    exit 1
fi

echo ""
echo "================================================"
echo "   ✓ Setup erfolgreich abgeschlossen!"
echo "================================================"
echo ""
echo "Deine Reading Diary Demo ist jetzt erreichbar unter:"
echo "  https://$DOMAIN"
echo ""
echo "Standard-Login:"
echo "  Passwort: demo123 (in /opt/reading-diary/start-server-linux.sh ändern)"
echo ""
echo "Nützliche Befehle:"
echo "  sudo systemctl status nginx          # Nginx Status"
echo "  sudo systemctl status reading-diary  # App Status"
echo "  sudo nginx -t                        # Config testen"
echo "  sudo systemctl reload nginx          # Nginx neu laden"
echo "  sudo certbot renew --dry-run         # Zertifikat-Erneuerung testen"
echo ""
echo "Logs:"
echo "  sudo tail -f /var/log/nginx/reading-diary-access.log"
echo "  sudo tail -f /var/log/nginx/reading-diary-error.log"
echo "  sudo journalctl -u reading-diary -f"
echo ""

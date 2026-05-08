# Deploying to a VPS with PuTTY

This guide assumes an Ubuntu VPS and that you connect with PuTTY over SSH.

## Upload through GitHub

On your computer:

```bash
git init
git add .
git commit -m "Initial Polymarket weather bot"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

On the VPS through PuTTY:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
git clone https://github.com/YOUR_USER/YOUR_REPO.git
cd YOUR_REPO
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Add:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
OPENWEATHER_API_KEY=your_openweather_key
```

Test:

```bash
python bot.py
```

## Run as a systemd service

Create a service file:

```bash
sudo nano /etc/systemd/system/polymarket-weather-bot.service
```

Paste this, changing `YOUR_USER` and path as needed:

```ini
[Unit]
Description=Polymarket Weather Telegram Bot
After=network-online.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/YOUR_REPO
EnvironmentFile=/home/YOUR_USER/YOUR_REPO/.env
ExecStart=/home/YOUR_USER/YOUR_REPO/.venv/bin/python /home/YOUR_USER/YOUR_REPO/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable polymarket-weather-bot
sudo systemctl start polymarket-weather-bot
sudo systemctl status polymarket-weather-bot
```

View logs:

```bash
journalctl -u polymarket-weather-bot -f
```

## HRRR dependency note

HRRR uses `herbie-data`, `xarray`, and `cfgrib`. If installation fails because of native GRIB dependencies, install:

```bash
sudo apt install -y libeccodes0
```

Then retry:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

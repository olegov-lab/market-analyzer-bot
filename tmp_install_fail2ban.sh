#!/bin/bash
apt-get install -y fail2ban
echo "FAIL2BAN_INSTALLED"
# Create SSH jail
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ssh
logpath = %(sshd_log)s
backend = systemd
EOF
systemctl restart fail2ban
systemctl enable fail2ban
echo "FAIL2BAN_CONFIGURED"
fail2ban-client status sshd 2>&1 || true

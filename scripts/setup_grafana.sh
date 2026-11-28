#!/usr/bin/env bash
# Install Grafana on the Raspberry Pi and load the PlantPulse dashboard (T-31).
#
# Run it on the Pi from the repository, as the user that owns the repository
# (it asks for sudo when needed). Safe to run again: it skips what is done.
#
#     bash scripts/setup_grafana.sh
#
# Then open http://<pi-address>:3000/ (first login admin / admin).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DB="$REPO/data/plantpulse.db"
PLUGIN="frser-sqlite-datasource"

echo "== 1/5 Grafana"
if ! dpkg -s grafana >/dev/null 2>&1; then
    sudo apt-get install -y apt-transport-https wget gpg
    sudo mkdir -p /etc/apt/keyrings
    wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor \
        | sudo tee /etc/apt/keyrings/grafana.gpg >/dev/null
    echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
        | sudo tee /etc/apt/sources.list.d/grafana.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y grafana
else
    echo "already installed"
fi
sudo apt-get install -y acl >/dev/null   # setfacl, for step 4

echo "== 2/5 SQLite plugin ($PLUGIN)"
# Newer Grafana packages may only ship "grafana cli", without the grafana-cli wrapper
gcli() {
    if command -v grafana-cli >/dev/null 2>&1; then
        sudo grafana-cli "$@"
    else
        sudo grafana cli --homepath /usr/share/grafana --config /etc/grafana/grafana.ini "$@"
    fi
}
if gcli plugins ls 2>/dev/null | grep -q "$PLUGIN"; then
    echo "already installed"
else
    gcli plugins install "$PLUGIN"
fi

echo "== 3/5 Data source and dashboard provisioning"
for kind in datasources dashboards; do
    sed "s|__REPO__|$REPO|g" "$REPO/config/grafana/provisioning/$kind/plantpulse.yaml" \
        | sudo tee "/etc/grafana/provisioning/$kind/plantpulse.yaml" >/dev/null
done

echo "== 4/5 Read access for the grafana user"
# The database must exist, even empty, so Grafana can open it.
(cd "$REPO" && python3 -m plantpulse.storage --db "$DB")
# Home folders are private on Raspberry Pi OS: let only the grafana user pass
# through the folders above the repository and read the database and dashboards.
dir="$REPO"
while [ "$dir" != "/" ]; do
    sudo setfacl -m u:grafana:x "$dir"
    dir="$(dirname "$dir")"
done
sudo setfacl -m u:grafana:rx "$REPO/data" "$REPO/config" "$REPO/config/grafana" \
    "$REPO/config/grafana/dashboards"
sudo setfacl -m u:grafana:r "$DB" "$REPO/config/grafana/dashboards/"*.json
# New files in data/ (the SQLite journal) are readable by grafana too
sudo setfacl -d -m u:grafana:r "$REPO/data"

echo "== 5/5 Start Grafana"
sudo systemctl enable grafana-server >/dev/null 2>&1
sudo systemctl restart grafana-server

address="$(hostname -I | awk '{print $1}')"
echo
echo "Grafana is starting: open http://${address}:3000/ (first login admin / admin),"
echo "then Dashboards > PlantPulse > PlantPulse – plant readings."

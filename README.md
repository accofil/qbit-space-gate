# qbit-space-gate

Kis szolgáltatás egy **kis lemezes, gyors „versenyző” qBittorrenthez** (pl. VPS), amely az
autobrr-től kapott torrenteket rögtön továbbadja egy nagy seedboxnak (pl. a
[qbit-aither-relay](https://github.com/accofil/qbit-aither-relay) szkripttel).

## qbit-space-gate – helykapu

Az autobrr a torrenteket **leállítva** adja hozzá (a művelet „paused” kapcsolójával), így semmi
nem töltődik le, amíg a kapu nem döntött. A kapu 0,5 másodpercenként néz rá, és minden új
torrentről egyszer dönt:

* **belefér** → elindítja. Belefér, ha a már beengedett (még a qBittorrentben lévő) torrentek
  teljes mérete a sajátjával együtt legfeljebb `limit_gb`, és minden futó letöltés befejezése
  után is marad `min_free_gb` szabad hely;
* **nem fér bele** → azonnal törli a listából, adatokkal együtt (0%-on, el sem indult).

Ha egy torrent már futva érkezik (pl. kézzel adtad hozzá) és nem fér bele, csak `safe_progress`
(alapból 5%) alatt törli, hogy soha ne lehessen belőle hit & run; efölött hagyja és naplózza.
A hely akkor szabadul fel, amikor a relay átküldte és törölte a torrentet.

## qbit-traffic-guard – havi forgalomkeret

Időzítve (5 percenként) a vnstat szerinti havi kimenő forgalom alapján állítja a qBittorrent
globális feltöltési korlátját: `soft_tb` alatt korlátlan, `soft_tb` és `hard_tb` között a
maradékot egyenletesen elosztja a hónap hátralevő részére, `hard_tb` felett csepegtet
(`trickle_kib`). A relay rsync-forgalmát nem korlátozza, de beleszámít.

## Telepítés

```bash
git clone https://github.com/accofil/qbit-space-gate.git
cd qbit-space-gate
sudo bash install.sh accofil
sudo nano /etc/qbit-space-gate/config.toml      # qBittorrent URL, felhasználó, jelszó, korlátok
sudo systemctl enable --now qbit-space-gate@accofil qbit-traffic-guard@accofil.timer
```

Napló: `~/.local/state/qbit-space-gate.log` (`START` / `DROP` / `OVER` sorok),
a forgalomőré: `journalctl -u qbit-traffic-guard@accofil`.

Tesztek: `python3 -m unittest discover -s tests`

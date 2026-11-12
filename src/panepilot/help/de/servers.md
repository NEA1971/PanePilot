# Server (FTP/SFTP)

PanePilot verbindet sich mit Servern über **FTP**, **FTP über TLS** (explizit oder implizit) und **SFTP** (über SSH), zum Beispiel mit dem NAS oder einer FTP-App auf dem Handy. Der Server erscheint dann ganz normal im Dateifenster.

## Seitenleiste „Server“
- Über **Ansicht ▸ Seitenleiste** bzw. per Rechtsklick in eine Seitenleiste schaltet man auf **Server** um – links oder rechts.
- Server lassen sich in **Ordnern** gruppieren und mit der Maus umsortieren.
- **Doppelklick** verbindet. Der Server wird im Dateifenster derselben Seite angezeigt.
- **Rechtsklick**:
  - auf einem Server: Verbinden, Trennen, Bearbeiten, Kopieren, Umbenennen, Löschen, Neuer Server, Neuer Ordner
  - auf einem Ordner: Neuer Server, Neuer Ordner, Umbenennen, Löschen (nur wenn leer)
- Ein verbundener Server ist **fett** und hat ein **grünes** Symbol. Die Pfadzeile zeigt die Adresse, z. B. `sftp://alice@192.168.1.10/Download`.

## Servermanager
**Datei ▸ Servermanager …** (oder „Bearbeiten …“ im Rechtsklick-Menü) – aufgebaut wie bei FileZilla:
- **Allgemein**: Protokoll, Server und Port, Verschlüsselung, Verbindungsart (normal, anonym, nach Passwort fragen, bei SFTP auch Schlüsseldatei), Benutzer, Passwort, Hintergrundfarbe des Dateifensters und Kommentar.
- **Erweitert**: Startordner auf dem Server und ein lokaler Ordner für das andere Fenster.
- **Übertragung**: Passiv (empfohlen) oder Aktiv – nur bei FTP.
- **Zeichensatz**: automatisch, UTF-8 erzwingen oder ein eigener Zeichensatz – nur bei FTP.

**Passwörter** speichert PanePilot im **Schlüsselbund** des Systems (unter GNOME der GNOME-Schlüsselbund), nicht in den Einstellungen. Gibt es keinen Schlüsselbund, fragt PanePilot beim Verbinden.

## Sicherheit
- **SFTP**: Beim ersten Verbinden zeigt PanePilot den Fingerabdruck des Servers. Ändert er sich später, kommt eine deutliche Warnung.
- **FTP über TLS**: Ein selbst ausgestelltes Zertifikat (z. B. von einer Handy-App) bestätigt man einmal; PanePilot merkt es sich.
- Reines **SCP** wird nicht unterstützt – fast jeder SSH-Server kann auch SFTP.

## Arbeiten auf dem Server
- **Kopieren/Verschieben** mit F5/F6 oder durch Ziehen zwischen den Fenstern lädt herunter bzw. hoch, auch ganze Ordner. Beim Verschieben wird die Quelle erst nach erfolgreicher Übertragung gelöscht.
- **Umbenennen**, **Neuer Ordner** und **Aktualisieren** wie gewohnt.
- **Löschen** ist auf dem Server immer **endgültig** (mit Rückfrage) – dort gibt es keinen Papierkorb.
- **Doppelklick auf eine Datei** lädt sie in einen temporären Ordner und öffnet sie mit dem Standardprogramm. Änderungen daran werden nicht zurückgeladen.
- Nicht möglich auf dem Server: Suche, Mehrfach-Umbenennen, Meta-Wizard, Prüfsummen, Archive, Terminal und Verzeichnisliste.
- Die Verbindung endet mit **Trennen**, beim Wechsel in einen lokalen Ordner im selben Fenster (z. B. über Favoriten oder „Zurück“) und beim Beenden. Bricht sie unterwegs ab, bietet PanePilot „Neu verbinden“ an.
- Beide Fenster können gleichzeitig mit verschiedenen Servern verbunden sein. Direkt von Server zu Server kopieren geht nicht.

## Übertragungsfenster
Übertragungen laufen im Hintergrund – man kann nebenbei weiterarbeiten.
- Oben: Dateien x von y, Datenmenge, Geschwindigkeit, Restzeit und ein Balken.
- Darunter: alle Dateien mit Status (wartet, läuft, fertig, Fehler mit Grund).
- Weitere Übertragungen werden **hinten angehängt**.
- Knöpfe: **Pause/Fortsetzen**, **Alles abbrechen**, **Markierte entfernen** (wartende) und **Erneut versuchen** (fehlgeschlagene).
- Mit **„Nach erfolgreichem Abschluss automatisch schließen“** schließt sich das Fenster von selbst – bei Fehlern nie.
- Gibt es eine Datei schon, kommt die gewohnte Rückfrage (Überschreiben, Überspringen, Umbenennen, „für alle“).

## Aus FileZilla übernehmen
**Einstellungen ▸ Allgemein ▸ Server ▸ Aus FileZilla importieren …** liest die Serverliste von FileZilla samt Ordnern und gespeicherten Passwörtern. Man wählt per Häkchen aus; Server mit gleichem Namen im selben Ordner werden übersprungen.

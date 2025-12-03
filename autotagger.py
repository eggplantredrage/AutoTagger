import sys
import os
import re
import json
import requests
from io import BytesIO
from urllib.parse import quote

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFileDialog, QMessageBox, QGroupBox,
    QComboBox, QDialog, QFormLayout, QTextBrowser
)
from PyQt5.QtGui import QPixmap, QImage, QFont
from PyQt5.QtCore import Qt
# IMPORTANT: APIC is now properly imported!
from mutagen.id3 import ID3, TPE1, TALB, TIT2, TDRC, TRCK, TCON, APIC, ID3NoHeaderError
from mutagen.mp3 import MP3


# Common ID3 genres
GENRES = [
    "Acoustic", "Alternative", "Anime", "Blues", "Classical", "Country", "Dance",
    "Disco", "Electronic", "Folk", "Funk", "Hip-Hop", "Indie", "Jazz", "Latin",
    "Lo-Fi", "Metal", "Pop", "Punk", "R&B", "Rap", "Reggae", "Rock", "Soul",
    "Soundtrack", "Techno", "Vocal"
]


class AboutDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("About Auto Tagger")
        self.setFixedSize(420, 340)
        layout = QVBoxLayout()

        # Try to load logo.png from the same directory as the script
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
        if os.path.isfile(logo_path):
            logo_label = QLabel()
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                # Scale to fit (max 120x120)
                scaled = pixmap.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                logo_label.setPixmap(scaled)
                logo_label.setAlignment(Qt.AlignCenter)
                layout.addWidget(logo_label)
            else:
                # Fallback if PNG is corrupt
                self._add_text_logo(layout)
        else:
            # Fallback if logo.png not found
            self._add_text_logo(layout)

        info = QTextBrowser()
        info.setHtml("""
        <p><b>Auto Tagger</b> – Smart MP3 Metadata Editor</p>
        <p><b>Features:</b></p>
        <ul>
            <li>Auto-fetch from MusicBrainz</li>
            <li>Embed album artwork</li>
            <li>Batch folder tagging</li>
            <li>ID3v1 / v2.3 / v2.4 support</li>
            <li>Drag &amp; drop loading</li>
            <li>Genre support + custom input</li>
        </ul>
        <p>Built with: <tt>Python • PyQt5 • Mutagen</tt></p>
        <p>By Kevin Leblanc (eggplant48) 2025</p>
        """)
        info.setOpenExternalLinks(False)
        info.setMaximumHeight(180)
        layout.addWidget(info)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self.setLayout(layout)

    def _add_text_logo(self, layout):
        logo = QLabel("🎧 AUTO TAGGER")
        logo.setFont(QFont("Monospace", 14, QFont.Bold))
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("color: #2c3e50;")
        layout.addWidget(logo)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self.setLayout(layout)


class AutoTagger(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Auto Tagger")
        self.setGeometry(100, 100, 720, 680)
        self.setAcceptDrops(True)

        self.current_file = None
        self.current_folder = None
        self.album_art_pixmap = None
        self.album_art_bytes = None
        self.id3_version = 3  # default: ID3v2.3

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        central.setLayout(layout)

        # File/Folder buttons
        top_layout = QHBoxLayout()
        self.btn_load_file = QPushButton("Load MP3 File")
        self.btn_load_file.clicked.connect(self.load_file)
        self.btn_load_folder = QPushButton("Load Folder")
        self.btn_load_folder.clicked.connect(self.load_folder)
        top_layout.addWidget(self.btn_load_file)
        top_layout.addWidget(self.btn_load_folder)
        layout.addLayout(top_layout)

        # ID3 Version selector
        id3_layout = QHBoxLayout()
        id3_layout.addWidget(QLabel("ID3 Version:"))
        self.id3_combo = QComboBox()
        self.id3_combo.addItems(["ID3v1", "ID3v2.3", "ID3v2.4"])
        self.id3_combo.setCurrentIndex(1)
        self.id3_combo.currentIndexChanged.connect(self.on_id3_version_change)
        id3_layout.addWidget(self.id3_combo)
        layout.addLayout(id3_layout)

        self.btn_auto_fetch = QPushButton("Auto-Fetch Info (MusicBrainz)")
        self.btn_auto_fetch.clicked.connect(self.auto_fetch_info)
        self.btn_auto_fetch.setEnabled(False)
        layout.addWidget(self.btn_auto_fetch)

        self.art_label = QLabel("No album art")
        self.art_label.setAlignment(Qt.AlignCenter)
        self.art_label.setMinimumHeight(200)
        self.art_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        layout.addWidget(self.art_label)

        # Tag editor
        group = QGroupBox("MP3 Tags")
        form_layout = QFormLayout()

        self.artist_edit = QLineEdit()
        self.album_edit = QLineEdit()
        self.title_edit = QLineEdit()
        self.year_edit = QLineEdit()
        self.track_edit = QLineEdit()
        self.genre_edit = QComboBox()
        self.genre_edit.setEditable(True)
        self.genre_edit.addItems(GENRES)

        form_layout.addRow("Artist:", self.artist_edit)
        form_layout.addRow("Album:", self.album_edit)
        form_layout.addRow("Title:", self.title_edit)
        form_layout.addRow("Year:", self.year_edit)
        form_layout.addRow("Track Number:", self.track_edit)
        form_layout.addRow("Genre:", self.genre_edit)

        group.setLayout(form_layout)
        layout.addWidget(group)

        # Action buttons
        btn_layout = QHBoxLayout()
        self.btn_fetch_art = QPushButton("Fetch Album Art")
        self.btn_fetch_art.clicked.connect(self.fetch_album_art)
        self.btn_save = QPushButton("Save Tags")
        self.btn_save.clicked.connect(self.save_tags)
        btn_layout.addWidget(self.btn_fetch_art)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(self.status_label)

        # Menu: About
        menu = self.menuBar()
        help_menu = menu.addMenu("Help")
        about_action = help_menu.addAction("About Auto Tagger")
        about_action.triggered.connect(self.show_about)

    def show_about(self):
        dialog = AboutDialog()
        dialog.exec_()

    def on_id3_version_change(self, index):
        self.id3_version = [1, 3, 4][index]

    # ─── DRAG & DROP ───────────────────────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
        if not paths:
            return

        if len(paths) == 1:
            path = paths[0]
            if os.path.isfile(path) and path.lower().endswith('.mp3'):
                self.load_single_file(path)
            elif os.path.isdir(path):
                self.load_folder_path(path)
        else:
            # Check if all are MP3s → treat as folder batch
            mp3_files = [p for p in paths if os.path.isfile(p) and p.lower().endswith('.mp3')]
            if mp3_files:
                self.load_folder_path(os.path.dirname(mp3_files[0]))
            else:
                # Or load first MP3
                for p in paths:
                    if os.path.isfile(p) and p.lower().endswith('.mp3'):
                        self.load_single_file(p)
                        break

    def load_single_file(self, path):
        self.current_file = path
        self.current_folder = None
        self.load_tags()
        self.btn_auto_fetch.setEnabled(True)
        self.status_label.setText(f"Loaded: {os.path.basename(path)}")

    def load_folder_path(self, path):
        self.current_folder = path
        self.current_file = None
        self.clear_fields()
        self.btn_auto_fetch.setEnabled(False)
        self.status_label.setText(f"Folder: {os.path.basename(path)}")

    # ─── UI CONTROL ────────────────────────────────────────────────
    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open MP3 File", "", "MP3 Files (*.mp3)")
        if file_path:
            self.load_single_file(file_path)

    def load_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder_path:
            self.load_folder_path(folder_path)

    def clear_fields(self):
        self.artist_edit.clear()
        self.album_edit.clear()
        self.title_edit.clear()
        self.year_edit.clear()
        self.track_edit.clear()
        self.genre_edit.setCurrentText("")
        self.art_label.setText("No album art")
        self.album_art_pixmap = None
        self.album_art_bytes = None

    def load_tags(self):
        if not self.current_file:
            return
        try:
            audio = MP3(self.current_file, ID3=ID3)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read file:\n{e}")
            return

        def get_tag(tag_key):
            tag = audio.get(tag_key)
            if not tag or not tag.text:
                return ""
            value = tag.text[0]
            if hasattr(value, 'text'):
                raw = str(value.text)
            else:
                raw = str(value)
            if tag_key == "TDRC":
                match = re.match(r'^(\d{4})', raw)
                return match.group(1) if match else raw
            return raw

        self.artist_edit.setText(get_tag("TPE1"))
        self.album_edit.setText(get_tag("TALB"))
        self.title_edit.setText(get_tag("TIT2"))
        self.year_edit.setText(get_tag("TDRC"))
        self.track_edit.setText(get_tag("TRCK"))
        self.genre_edit.setEditText(get_tag("TCON"))

        if "APIC:" in audio:
            apic = audio["APIC:"]
            img = QImage.fromData(apic.data)
            pixmap = QPixmap.fromImage(img).scaled(200, 200, Qt.KeepAspectRatio)
            self.art_label.setPixmap(pixmap)
            self.album_art_pixmap = pixmap
            self.album_art_bytes = apic.data
        else:
            self.art_label.setText("No album art")
            self.album_art_pixmap = None
            self.album_art_bytes = None

    # ─── MUSICBRAINZ ───────────────────────────────────────────────
    def parse_filename(self, filepath):
        basename = os.path.splitext(os.path.basename(filepath))[0]
        if " - " in basename:
            parts = basename.split(" - ", 1)
            return parts[0].strip(), parts[1].strip()
        return "", basename

    def auto_fetch_info(self):
        if not self.current_file:
            return
        artist = self.artist_edit.text().strip()
        title = self.title_edit.text().strip()
        if not (artist and title):
            fn_artist, fn_title = self.parse_filename(self.current_file)
            artist = artist or fn_artist
            title = title or fn_title
        if not artist or not title:
            QMessageBox.warning(self, "Not Enough Info", "Need Artist and Title to search.")
            return

        try:
            query = f"artist:\"{artist}\" recording:\"{title}\""
            url = f"https://musicbrainz.org/ws/2/recording/?query={quote(query)}&fmt=json&limit=1"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if not data.get("recordings"):
                QMessageBox.information(self, "No Match", "No recording found on MusicBrainz.")
                return

            rec = data["recordings"][0]
            new_artist = rec["artist-credit"][0]["name"] if rec.get("artist-credit") else artist
            new_title = rec["title"]
            new_album = self.album_edit.text()
            new_year = self.year_edit.text()
            new_track = self.track_edit.text()

            if rec.get("releases"):
                release = rec["releases"][0]
                new_album = release.get("title", new_album)
                if "date" in release:
                    year_match = re.match(r'^(\d{4})', release["date"])
                    if year_match:
                        new_year = year_match.group(1)

            self.artist_edit.setText(new_artist)
            self.album_edit.setText(new_album)
            self.title_edit.setText(new_title)
            self.year_edit.setText(new_year)
            self.track_edit.setText(new_track)
            self.status_label.setText("✅ Auto-fetched metadata from MusicBrainz!")

        except Exception as e:
            QMessageBox.critical(self, "Fetch Error", f"Auto-fetch failed:\n{str(e)}")

    def fetch_album_art(self):
        if self.current_folder:
            QMessageBox.warning(self, "Folder Mode", "Load a single file to fetch album art.")
            return
        artist = self.artist_edit.text().strip()
        album = self.album_edit.text().strip()
        if not artist or not album:
            QMessageBox.warning(self, "Missing Info", "Enter Artist and Album.")
            return

        try:
            query = f"release:\"{album}\" artist:\"{artist}\""
            url = f"https://musicbrainz.org/ws/2/release/?query={quote(query)}&fmt=json&limit=1"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if not data.get("releases"):
                QMessageBox.information(self, "Not Found", "No release found.")
                return

            mbid = data["releases"][0]["id"]
            cover_url = f"https://coverartarchive.org/release/{mbid}/front"
            img_resp = requests.get(cover_url, timeout=10)
            if img_resp.status_code == 200:
                self.album_art_bytes = img_resp.content
                img = QImage.fromData(self.album_art_bytes)
                pixmap = QPixmap.fromImage(img).scaled(200, 200, Qt.KeepAspectRatio)
                self.art_label.setPixmap(pixmap)
                self.album_art_pixmap = pixmap
                self.status_label.setText("🖼️ Album art fetched!")
            else:
                QMessageBox.information(self, "No Art", "No album art available.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to fetch album art:\n{str(e)}")

    # ─── SAVE ──────────────────────────────────────────────────────
    def save_tags(self):
        if self.current_file:
            self._save_single_file(self.current_file)
            self.status_label.setText("✅ Tags saved!")
        elif self.current_folder:
            mp3_files = [
                os.path.join(self.current_folder, f)
                for f in os.listdir(self.current_folder)
                if f.lower().endswith('.mp3')
            ]
            if not mp3_files:
                QMessageBox.warning(self, "No MP3s", "No MP3 files found in folder.")
                return
            for mp3 in mp3_files:
                self._save_single_file(mp3, suppress_reload=True)
            self.status_label.setText(f"✅ Saved tags for {len(mp3_files)} files!")
        else:
            QMessageBox.warning(self, "No Target", "Load a file or folder first.")

    def _save_single_file(self, filepath, suppress_reload=False):
        try:
            try:
                audio = MP3(filepath, ID3=ID3)
            except ID3NoHeaderError:
                audio = MP3(filepath)
                audio.add_tags(ID3=ID3)
        except Exception as e:
            print(f"⚠️ Skip {filepath}: {e}")
            return

        # Clear tags
        for tag in ["TPE1", "TALB", "TIT2", "TDRC", "TRCK", "TCON", "APIC"]:
            audio.tags.delall(tag)

        # Set new tags
        if self.artist_edit.text():
            audio.tags.add(TPE1(encoding=3, text=self.artist_edit.text()))
        if self.album_edit.text():
            audio.tags.add(TALB(encoding=3, text=self.album_edit.text()))
        if self.title_edit.text():
            audio.tags.add(TIT2(encoding=3, text=self.title_edit.text()))
        if self.year_edit.text():
            audio.tags.add(TDRC(encoding=3, text=self.year_edit.text()))
        if self.track_edit.text():
            audio.tags.add(TRCK(encoding=3, text=self.track_edit.text()))
        if self.genre_edit.currentText():
            audio.tags.add(TCON(encoding=3, text=self.genre_edit.currentText()))

        # Embed album art if available
        if self.album_art_bytes:
            mime = 'image/jpeg'
            if self.album_art_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
                mime = 'image/png'
            audio.tags.add(APIC(
                encoding=3,
                mime=mime,
                type=3,
                desc='Cover',
                data=self.album_art_bytes
            ))

        # Save with selected ID3 version
        v1 = (1 if self.id3_version == 1 else 0)
        v2_version = self.id3_version if self.id3_version != 1 else 3
        try:
            audio.save(v1=v1, v2_version=v2_version)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save {os.path.basename(filepath)}:\n{e}")

        if not suppress_reload and filepath == self.current_file:
            self.load_tags()


# ─── MAIN ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AutoTagger()
    window.show()
    sys.exit(app.exec_())
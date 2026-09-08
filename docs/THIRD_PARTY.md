# Сторонні компоненти

MIT-ліцензія в корені стосується коду Revolution. Нижче компоненти, що зберігають власні авторські права та умови. Тексти ліцензій Python-пакетів і Qt додаються до каталогу `licenses` у релізі.

| Компонент | Ліцензія / джерело |
|---|---|
| Python | PSF — https://www.python.org/psf/license/ |
| PySide6 / Shiboken / Qt | LGPL-3.0 (відповідні модулі) — https://doc.qt.io/qtforpython-6/licenses.html |
| Qt WebEngine / Chromium | Qt LGPL-3.0 та ліцензії Chromium-компонентів — https://doc.qt.io/qt-6/qtwebengine-licensing.html |
| minecraft-launcher-lib | BSD-2-Clause — https://codeberg.org/JakobDev/minecraft-launcher-lib |
| Requests | Apache-2.0 — https://github.com/psf/requests |
| keyring | MIT — https://github.com/jaraco/keyring |
| pypresence | MIT — https://github.com/qwertyquerty/pypresence |
| truststore | MIT — https://github.com/sethmlarson/truststore |
| dnspython | ISC — https://github.com/rthalley/dnspython |
| cryptography | Apache-2.0 / BSD-3-Clause — https://cryptography.io/en/latest/ |
| cffi / pycparser | MIT / BSD-3-Clause, тексти у licenses |
| Lucide | ISC — https://lucide.dev/license |
| PyInstaller bootloader | GPL-2.0-or-later з винятком для розповсюдження — https://pyinstaller.org/en/stable/license.html |

Qt/PySide постачаються немодифікованими динамічними бібліотеками у `_internal`; вони можуть бути замінені сумісними модифікованими версіями. Код лаунчера та файл збірки доступні в архіві вихідного коду. Умови MIT не обмежують права щодо бібліотек LGPL, зокрема модифікацію, заміну та зворотне проєктування для налагодження таких модифікацій. Вихідні коди відповідних бібліотек: https://download.qt.io/archive/qt/6.10/6.10.2/ і https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.2-src/ . Перевірте вимоги до власного розповсюдження при публікації зміненої збірки.

Minecraft/NeoForge/Java не включено в ZIP лаунчера, вони мають окремі ліцензії та завантажуються з джерел власників. Папка modpack містить 97 наданих користувачем JAR-файлів із власними ліцензіями; перелік у MODPACK.md. Фоновий арт створено для цього проєкту вбудованим imagegen; опис запиту в `ART.md`.

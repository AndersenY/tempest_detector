# ПЭМИН Детектор

Графическое приложение для поиска признаков ПЭМИН-сигналов в радиоспектре с помощью SDR-приёмников. Программа измеряет фон, измеряет спектр при включённом тестовом сигнале, строит разностную панораму и помогает классифицировать найденные частоты.

Проект написан на Python с интерфейсом на PyQt6. В качестве источников данных поддерживаются RTL-SDR, HackRF One и встроенный демо-симулятор для проверки работы без оборудования.

## Демонстрация

https://github.com/user-attachments/assets/c9bdd9d8-52c4-43c6-9acf-9206a6a280df

## Возможности

- измерение спектра в заданном диапазоне частот;
- поиск кандидатов методом разности панорам `ON - OFF`;
- быстрый режим без дополнительной верификации;
- метод поиска по гармоникам;
- режим Live-обзора спектра с пользовательскими метками;
- нулевой обзор для наблюдения выбранной частоты во времени;
- работа с RTL-SDR и HackRF One;
- демо-симулятор без SDR-оборудования;
- ручное, полуавтоматическое и автоматическое управление тестовым сигналом;
- TCP-сервер удалённого управления тестовым клиентом;
- экспорт отчёта в CSV и спектров в NPZ.

## Структура проекта

```text
.
├── main.py                         # точка входа приложения
├── requirements.txt                # зависимости для pip
├── environment.yml                 # conda-окружение
├── core/
│   ├── backends/                   # источники спектра: RTL-SDR, HackRF, симулятор
│   ├── methods/                    # алгоритмы обнаружения
│   ├── config.py                   # настройки измерений
│   ├── models.py                   # модели спектра и сигналов
│   └── remote_control_server.py    # TCP-сервер управления тестовым клиентом
├── gui/                            # интерфейс приложения
├── image/                          # иконка приложения
├── lib/                            # DLL для Windows
└── tempest_for_eliza/              # тестовый генератор/демонстрационные материалы
```

## Требования

- Python 3.11 или новее;
- SDR-приёмник RTL-SDR или HackRF One, если нужен реальный захват спектра;
- установленные системные драйверы/библиотеки для выбранного SDR;
- Linux или Windows.

Основные Python-зависимости:

- `PyQt6`;
- `numpy`;
- `pyqtgraph`;
- `scipy`;
- `sounddevice`;
- `pyrtlsdr`.

## Установка через pip

1. Клонируйте или скачайте проект.

```bash
git clone https://github.com/AndersenY/tempest_detector.git
```

2. Перейдите в папку проекта:

```bash
cd /path/to/pemin_detector
```

3. Создайте виртуальное окружение:

Linux:

```bash
python3 -m venv sdr
```

Windows:

```powershell
python.exe -m venv sdr
```

4. Активируйте окружение.

Linux/macOS:

```bash
source sdr/bin/activate
```

Windows PowerShell:

```powershell
./sdr/Scripts/activate
```

5. Установите зависимости:

```bash
pip install -r requirements.txt
```

## Установка через conda

Создать окружение из файла:

```bash
conda env create -f environment.yml
conda activate sdr
```

Обновить уже созданное окружение:

```bash
conda env update -f environment.yml
```

## Системные зависимости для SDR

### RTL-SDR

Для RTL-SDR нужен доступ к устройству и библиотека `librtlsdr`.

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install rtl-sdr librtlsdr-dev
```

Если устройство занято стандартным DVB-драйвером Linux, его обычно отключают через blacklist. После настройки переподключите донгл.

На Windows установите WinUSB-драйвер для RTL-SDR, например через Zadig. В проекте уже есть DLL в папке `lib/`, которые используются при запуске на Windows.

### HackRF One

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install hackrf libhackrf-dev
```

На Windows приложение ищет `hackrf-0.dll` и `libusb-1.0.dll` в папке `lib/`.

## Запуск

Из активированного окружения выполните:

```bash
python main.py
```

На Linux при первом запуске приложение создаёт desktop-файл `pemin-detector.desktop` в `~/.local/share/applications`, чтобы его можно было запускать из меню приложений.

## Готовая сборка для Windows

Для Windows подготовлен архив:

```text
app_windows_server.7z
```

Внутри архива находится приложение, уже скомпилированное через PyInstaller. Для запуска Python и установка зависимостей из `requirements.txt` не требуются.

Порядок запуска:

1. Скачайте или скопируйте `app_windows_server.7z` на компьютер с Windows.
2. Распакуйте архив в удобную папку.
3. Откройте распакованную папку с приложением.
4. Запустите файл:

```text
PEMIN_Detector.exe
```

Если Windows показывает предупреждение SmartScreen для неизвестного приложения, выберите дополнительную информацию и разрешите запуск только если архив получен из доверенного источника.

Для работы с реальным SDR-оборудованием на компьютере всё равно должны быть установлены системные USB-драйверы для RTL-SDR или HackRF One. DLL-библиотеки включены в сборку, но они не заменяют драйвер устройства в системе.


## Запуск в Docker

## Сборка образа

```bash
docker build -t pemin-detector .
```

---

## Быстрый старт (демо-режим)

Если SDR-оборудование не подключено, приложение работает встроенном симуляторе:

```bash
xhost +local:docker
docker run -it --rm \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    pemin-detector
```

---

## Подключение USB-устройств SDR

### Linux

Для доступа к USB-устройству из контейнера нужно пробросить `/dev/bus/usb`:

```bash
docker run -it --rm \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    --device=/dev/bus/usb \
    pemin-detector
```

#### Проверка, что устройство видно

Подключите SDR и выполните на хосте:

```bash
lsusb
```

Пример вывода с RTL-SDR:

```
Bus 001 Device 005: ID 0bda:2838 Realtek Semiconductor Corp. RTL2838 DVB-T
```

Пример вывода с HackRF:

```
Bus 001 Device 004: ID 1d50:6089 OpenMoko, Inc. HackRF One
```

Убедитесь, что `--device=/dev/bus/usb` передан в `docker run`.

#### udev-правила (рекомендуется)

Чтобы не прописывать `--device` вручную каждый раз, добавьте udev-правило на хосте:

RTL-SDR:

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="0bda", ATTR{idProduct}=="2838", MODE="0666"' | sudo tee /etc/udev/rules.d/20-rtlsdr.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

HackRF:

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="6089", MODE="0666"' | sudo tee /etc/udev/rules.d/20-hackrf.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

После этого переподключите устройство. Теперь можно запускать без `--device`:

```bash
docker run -it --rm \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    --device=/dev/bus/usb \
    pemin-detector
```

#### Права доступа

Если приложение не видит устройство, проверьте права:

```bash
ls -la /dev/bus/usb/XXX/YYY
```

Если права `root:root` и `0600`, добавьте себя в группу `plugdev`:

```bash
sudo usermod -aG plugdev $USER
```

Перелогиньтесь. Или запускайте контейнер от root (по умолчанию в образе).

## TCP-сервер удалённого управления

Приложение поднимает TCP-сервер на порту `62000`. Для доступа извне контейнера пробросьте порт:

```bash
docker run -it --rm \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    --device=/dev/bus/usb \
    -p 62000:62000 \
    pemin-detector
```

Или используйте `--network host` (пробрасывать порты не нужно):

```bash
docker run -it --rm --network host \
    --device=/dev/bus/usb \
    pemin-detector
```

---

## Полный пример запуска

Linux, RTL-SDR, с GUI и удалённым управлением:

```bash
xhost +local:docker
docker run -it --rm \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    --device=/dev/bus/usb \
    -p 62000:62000 \
    pemin-detector
```

---

## Решение проблем

### `qt.qpa.xcb: could not connect to display`

Контейнер не может подключиться к X11. Убедитесь что:

1. Выполнили `xhost +local:docker` на хосте
2. Передали `-e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix`

### `usb_open: error finding default device`

USB-устройство не проброшено в контейнер. Добавьте `--device=/dev/bus/usb`.

### RTL-SDR не обнаруживается

1. Проверьте `lsusb` на хосте
2. Отключите DVB-драйвер (см. раздел RTL-SDR)
3. Проверьте права на `/dev/bus/usb`

### HackRF не обнаруживается

1. Проверьте `lsusb` на хосте
2. Установите `libhackrf-dev` на хосте
3. Проверьте права на `/dev/bus/usb`

### `update-desktop-database: not found`

Не критично. Сообщение игнорируется. Для подавления установите `desktop-file-utils` на хосте.


## Сборка exe-файла для Windows

Сборку лучше выполнять на Windows, потому что PyInstaller собирает исполняемый файл под текущую операционную систему.

1. Перейдите в папку проекта:

```powershell
cd путь\к\папке\проекта
```

2. Создайте виртуальное окружение:

```powershell
python -m venv sdr
```

3. Активируйте окружение:

```powershell
./sdr/Scripts/activate
```

4. Установите зависимости:

```powershell
pip install -r requirements.txt
```

5. Убедитесь, что приложение запускается:

```powershell
python main.py
```

Если приложение запускается без ошибок, можно переходить к сборке.

6. Создайте директорию app и перейдите в нее:

```powershell
mkdir app
cd app
```

7. Соберите приложение с помощью PyInstaller:

```powershell
pyinstaller --noconfirm --clean --windowed --name "PEMIN_Detector" --icon "..\image\icon.ico" --add-data "..\image;image" --add-binary "..\lib\hackrf-0.dll;lib" --add-binary "..\lib\libusb-1.0.dll;lib" --add-binary "..\lib\libwinpthread-1.dll;lib" --add-binary "..\lib\rtlsdr.dll;lib" --distpath "." --workpath "build" --specpath "." "..\main.py"
```

Готовый файл будет находиться в:

```text
dist\PEMIN_Detector\PEMIN_Detector.exe
```

После сборки в папке проекта появятся следующие файлы и папки:

```text
build\
dist\
PEMIN_Detector.spec
```

### Папка `build`

```text
build\
```

Это временная служебная папка PyInstaller. В ней находятся промежуточные файлы, которые используются во время сборки приложения.

Эту папку не нужно переносить на другой компьютер. После успешной сборки её можно удалить.

### Папка `dist`

```text
dist\
```

Это основная папка с готовым собранным приложением.

Готовый `.exe` будет находиться здесь:

```text
dist\PEMIN_Detector\PEMIN_Detector.exe
```

Именно папку:

```text
dist\PEMIN_Detector\
```

нужно переносить на другой компьютер, если приложение собрано не в один файл. Внутри неё будут находиться сам `.exe`, служебные файлы Python, добавленные изображения и DLL-библиотеки из папки `lib`.

### Файл `PEMIN_Detector.spec`

```text
PEMIN_Detector.spec
```

Это файл конфигурации сборки PyInstaller. В нём сохраняются параметры сборки: имя приложения, подключённые файлы, библиотеки, иконка и другие настройки.

Обычно вручную его менять не нужно. Если требуется полностью пересобрать приложение с нуля, этот файл можно удалить вместе с папками `build` и `dist`.

### Очистка перед повторной сборкой

Если нужно пересобрать приложение заново, можно удалить старые результаты сборки:

```powershell
Remove-Item -Recurse -Force build, dist
Remove-Item -Force *.spec
```

После этого снова выполните команду сборки PyInstaller.

Для работы с RTL-SDR или HackRF на другом компьютере также нужны установленные USB-драйверы устройств. DLL из папки `lib/` попадают в сборку командой выше, но наличие DLL не заменяет установку драйверов устройств в системе.

## Быстрый старт

1. Запустите приложение:

```bash
python main.py
```

2. В меню **Устройство** выберите источник спектра:
   - `RTL-SDR`;
   - `HackRF One`;
   - демо-режим/симулятор, если оборудования нет.

3. Задайте диапазон частот, порог обнаружения, усиление и число усреднений.

4. Выберите режим поиска:
   - **Метод разности панорам** — основной режим с измерением фона, сигнала и верификацией;
   - **Быстрый режим** — поиск без верификации;
   - **Метод поиска по гармоникам** — анализ кандидатов по гармонической структуре;
   - **Симулятор** — проверка алгоритмов без SDR.

5. Нажмите кнопку запуска измерения и следуйте подсказкам интерфейса:
   - сначала измеряется фон при выключенном тестовом сигнале;
   - затем включается тестовый сигнал и измеряется спектр;
   - найденные частоты появляются в таблице и на графике;
   - при полном режиме выполняются проверки В1 и В2.

## Удалённое управление тестовым клиентом

При запуске приложение поднимает TCP-сервер на порту `62000`. Адрес отображается в интерфейсе во вкладке удалённого управления.

Для автоматизации включения и выключения тестового режима используется отдельный удалённый клиент:

[AndersenY/tempest_test_mode_client](https://github.com/AndersenY/tempest_test_mode_client)

Клиент запускается на устройстве, которое управляет тестовым сигналом, подключается к детектору по адресу `IP:62000` и получает команды от основного приложения. Это позволяет не переключать тестовый режим вручную во время измерений: детектор сам отправляет команду включения перед захватом `ON` и команду выключения перед проверкой фона.

Сервер отправляет клиентам JSON-команды:

```json
{"cmd": "test_start"}
{"cmd": "test_stop"}
{"cmd": "ping"}
```

Клиент должен отвечать подтверждением:

```json
{"status": "ack", "active": true}
```

Это используется в полуавтоматическом и автоматическом режимах, чтобы синхронизировать включение/выключение тестового сигнала с измерениями.

Типовой сценарий работы:

1. Запустите ПЭМИН Детектор на компьютере с SDR.
2. Откройте вкладку удалённого управления и посмотрите адрес сервера.
3. Запустите `tempest_test_mode_client` на тестовом устройстве и укажите адрес детектора.
4. Дождитесь появления подключённого клиента в интерфейсе.
5. Выберите полуавтоматический или автоматический режим измерения.

Если клиент не подключён, приложение продолжит работать в ручном режиме: пользователь сам включает и выключает тестовый сигнал по подсказкам интерфейса.

## Экспорт результатов

В приложении доступны два варианта сохранения:

- CSV-отчёт с таблицей найденных сигналов;
- NPZ-архив со спектрами `ON`, `OFF`, разностью и параметрами найденных сигналов.

Экспорт спектра доступен после выполнения измерения.

## Возможные проблемы

### Приложение не видит RTL-SDR

- проверьте, что устройство подключено;
- убедитесь, что оно не занято другой программой;
- на Linux проверьте права доступа к USB-устройству;
- на Windows проверьте драйвер WinUSB.

### Ошибка `libhackrf.so не найден`

Установите системную библиотеку HackRF:

```bash
sudo apt install libhackrf-dev
```

### Ошибка импорта PyQt6 или других библиотек

Проверьте, что активировано нужное окружение, затем повторите установку:

```bash
pip install -r requirements.txt
```

### Нет SDR-оборудования

Используйте встроенный демо-симулятор. Он генерирует синтетический спектр с фоном и гармоническими сигналами, поэтому подходит для проверки интерфейса и алгоритмов.

### Ошибка `rtlsdr_set_dithering` undefined symbol

При запуске приложения возникает ошибка:

```
AttributeError: /lib/x86_64-linux-gnu/librtlsdr.so: undefined symbol: rtlsdr_set_dithering
```

#### Причина

Bundled `pyrtlsdr 0.5.0` вызывает `rtlsdr_set_dithering` при импорте, но системная `librtlsdr 2.0.1` (Ubuntu 24.04 noble) не эксппортирует этот символ. Функция `rtlsdr_set_dithering` была добавлена в более поздних коммитах librtlsdr, которых нет в пакете из стандартного репозитория.

Аналогичная проблема может возникнуть с GPIO-функциями (`rtlsdr_set_gpio_output`, `rtlsdr_set_gpio_input`, `rtlsdr_set_gpio_bit` и др.), которые также отсутствуют в `librtlsdr 2.0.1`.

#### Решение

Обернуть вызовы отсутствующих функций в `try/except AttributeError` в файле:

```
sdr/lib/python3.12/site-packages/rtlsdr/librtlsdr.py
```

Найти блоки:
```python
# RTLSDR_API int rtlsdr_set_dithering(rtlsdr_dev *dev, int on)
f = librtlsdr.rtlsdr_set_dithering
f.restype, f.argtypes = c_int, [p_rtlsdr_dev, c_int]
```

Заменить на:
```python
# RTLSDR_API int rtlsdr_set_dithering(rtlsdr_dev *dev, int on)
try:
    f = librtlsdr.rtlsdr_set_dithering
    f.restype, f.argtypes = c_int, [p_rtlsdr_dev, c_int]
except AttributeError:
    pass
```

Аналогично для всех GPIO-функций (`rtlsdr_set_gpio_output`, `rtlsdr_set_gpio_input`, `rtlsdr_set_gpio_bit`, `rtlsdr_get_gpio_bit`, `rtlsdr_set_gpio_byte`, `rtlsdr_get_gpio_byte`, `rtlsdr_set_gpio_status`).

### Ошибка `PortAudio library not found`

При запуске приложения возникает ошибка:

```
OSError: PortAudio library not found
```

#### Причина

Пакет `sounddevice` (используется в `core/audio_monitor.py` для тон-монитора ПЭМИН-сигнала) зависит от системной библиотеки PortAudio. На Ubuntu/Debian по умолчанию PortAudio не установлен.

#### Решение

Установите системную библиотеку:

Ubuntu/Debian:
```bash
sudo apt install libportaudio2
```

## Примечание

Проект предназначен для учебных, исследовательских и демонстрационных задач по анализу побочных электромагнитных излучений. Корректность измерений зависит от SDR-приёмника, антенны, экранирования помещения, выбранного диапазона, калибровки и методики проведения эксперимента.

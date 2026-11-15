# Help add your BMS: diagnostic captures

OpenBMS Monitor reads JK BMS today. Support for **JBD / Xiaoxiang**,
**Daly / 100Balance** and **ANT** is being added, and the fastest way to get
there is a short recording from a real device. You do not need to install
anything else or know anything about Bluetooth.

## How to record (about 2 minutes)

1. Install the latest `OpenBmsMonitor-Setup-x.y.z.exe` from
   [Releases](https://github.com/linux2020l/OpenBMS-Monitor/releases)
   (Windows 10/11 with Bluetooth).
2. **Close the BMS app on your phone** (or turn off Bluetooth on the phone).
   A BMS accepts only one Bluetooth connection.
3. Start the app. If it asks to choose a BMS, just close that window.
4. Open the menu (right-click the widget or the tray icon) and choose
   **Record diagnostics…** (also in Settings).
5. Pick your BMS in the list. If it is not shown, tick **Show all devices**.
   Check that **BMS brand** is right, then press **Start recording**.
6. Write down what the phone app showed shortly before (SOC, voltage,
   current, a few cell voltages, temperatures). It helps to verify the
   decoding.
7. After 60 s the file is saved to `Documents\OpenBMS Monitor\`
   (`bms-capture-<brand>-<date>.txt`). Press **Open folder**.
8. [Open an issue](https://github.com/linux2020l/OpenBMS-Monitor/issues/new?template=bms-capture.yml)
   and attach the file, or send it to the developer.

Even if the BMS sends no data (wrong brand, unknown model), please share
the file: it contains the device's Bluetooth service table, which shows
what kind of BMS it is.

## Is it safe?

- The app sends **only read requests** taken from well-known open-source
  projects ([esphome-jbd-bms](https://github.com/syssi/esphome-jbd-bms),
  [esphome-ant-bms](https://github.com/syssi/esphome-ant-bms),
  [aiobmsble](https://github.com/patman15/aiobmsble)). Every frame it may
  send is listed in the code and checked before sending; there is no code
  that changes BMS settings, switches MOSFETs or sends passwords.
- The file contains the raw Bluetooth traffic. The **MAC address is not
  written**, and for JK the serial number and passcodes are overwritten.
  The device's Bluetooth **name stays** in the file; rename it in the phone
  app first if it contains something personal.

## What the file looks like

```
# jkbms_widget capture 2026-11-15T00:41:15
# app 0.4.0 bleak=1.1.1
# driver jbd
# brand JBD / Xiaoxiang (protocol from esphome-jbd-bms + aiobmsble)
# device name='JBD-SP04S028' (address removed)
# GATT table: ...
    1.204 TX h=0x0015 len=  7 DD A5 05 00 FF FB 77
    1.391 RX h=0x0011 len= 20 DD 05 00 10 ...
```

Developers: `python -m jkbms_widget replay <file> --speed 0` decodes it with
the driver named in the header.

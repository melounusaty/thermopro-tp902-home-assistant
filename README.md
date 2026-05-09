# ThermoPro TP90X Home Assistant Custom Integration
[![version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmelounusaty%2Fthermopro-tp90X-home-assistant%2Fmain%2Fcustom_components%2Ftp90x_multi%2Fmanifest.json&query=%24.version&label=version&color=slateblue)](https://github.com/melounusaty/thermopro-tp90X-home-assistant/releases/latest)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?logo=homeassistantcommunitystore&logoColor=white)](https://github.com/hacs/integration)

This custom integration adds support for the ThermoPro **TP90X** Bluetooth thermometer family in Home Assistant through a custom component placed in `custom_components/tp90x_multi/`.

It currently supports:

- **TP902** — fully supported.
- **TP904** — experimental support.

The integration uses a Home Assistant config entry, Bluetooth support, and sensor entities for the active probe channels exposed by the selected model.

<img width="882" height="962" alt="image" src="https://github.com/user-attachments/assets/26153499-e762-452b-87ae-eb834ea2f3b3" />

## TP90X protocol libraries

This integration is based on two ThermoPro BLE protocol projects:

- The original TP902 BLE protocol library from [`petrkr/thermopro-tp902`](https://github.com/petrkr/thermopro-tp902)
- The extended TP90X family library from [`dermdaly/thermopro-tp90x`](https://github.com/dermdaly/thermopro-tp90x)

The newer TP90X library introduces a shared `TP90xBase` implementation with model-specific subclasses for `TP902` and `TP904`, which is what makes it practical to support more than one TP90-series device in the same integration.

## What this integration provides

After installation and setup, the integration creates one ThermoPro device in Home Assistant and exposes entities based on the model you selected during setup.

### TP902

For **TP902**, the integration provides:

- `Probe 1` — temperature sensor
- `Probe 2` — temperature sensor
- `Battery` — diagnostic battery sensor
- `Units` — select entity for Celsius / Fahrenheit
- `Alarm sound` — switch entity
- `Probe 1 alarm` — switch entity
- `Probe 1 Min` — number entity
- `Probe 1 Max` — number entity
- `Probe 2 alarm` — switch entity
- `Probe 2 Min` — number entity
- `Probe 2 Max` — number entity

Only Probe 1 and Probe 2 are created for TP902 in the current integration, since those are the channels used in the Home Assistant implementation and the remaining TP902 channels are not useful for this setup.

### TP904

For **TP904**, the integration currently provides:

- Probe temperature sensors based on the TP904 model
- `Battery` — diagnostic battery sensor
- `Units` — select entity for Celsius / Fahrenheit
- `Alarm sound` — switch entity

TP904 alarm configuration is currently treated as **experimental** and is not exposed with the same min/max controls used by TP902, because the TP904 library indicates that parts of its settings behavior differ from the TP902 implementation.

## Folder contents

Place the integration in this path inside your Home Assistant config directory:

```text
config/
└── custom_components/
    └── tp90x_multi/
        ├── __init__.py
        ├── manifest.json
        ├── config_flow.py
        ├── device.py
        ├── sensor.py
        ├── select.py
        ├── switch.py
        ├── number.py
        ├── brand/
        │   ├── icon.png
        │   ├── icon@2x.png
        │   ├── logo.png
        │   └── logo@2x.png
        └── tp90x/
            ├── __init__.py
            ├── enums.py
            ├── tp902.py
            ├── tp904.py
            └── tp90xbase.py
```

The `tp90x_multi` folder is the Home Assistant custom integration itself. Home Assistant loads the integration from that directory based on the integration domain and `manifest.json`.

## Installation

### HACS (recommended)

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=melounusaty&repository=thermopro-tp90X-home-assistant&category=integration" target="_blank"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and open this repository inside HACS." /></a>

### Manual

1. Copy the whole `tp90x_multi` folder into `config/custom_components/` in your Home Assistant installation so the final path is `config/custom_components/tp90x_multi/`.
2. Restart Home Assistant so it discovers the custom integration and loads its manifest and config flow.
3. If you are upgrading from an older TP902-only version, replace the whole folder rather than mixing old and new files.

## Add the thermometer

Before adding the device, make sure the thermometer is powered on, close to a Bluetooth adapter or Bluetooth proxy that Home Assistant can use, and not currently connected to the ThermoPro mobile app.

### Find the thermometer MAC address

1. Open **Settings → Bluetooth → Advertisements**.
2. Search for the thermometer and copy its MAC address.

### Add it in Home Assistant

1. Open **Settings → Devices & Services**.
2. Click **Add Integration**.
3. Search for **ThermoPro TP90X**.
4. Enter the thermometer Bluetooth MAC address, for example `A4:46:1C:AC:61:51`.
5. Enter a friendly device name such as `Kitchen Thermometer`.
6. Select the device model:
   - `TP902`
   - `TP904 (experimental)`
7. Finish the setup flow.

The integration stores the MAC address as the unique identifier for the config entry, which is the recommended pattern for local Bluetooth devices.

## Naming in Home Assistant

This integration uses the following naming pattern:

- **Integration name**: `ThermoPro TP90X`
- **Device manufacturer**: `ThermoPro`
- **Device model**: `TP902` or `TP904`
- **Device name**: your chosen friendly name, for example `Kitchen Thermometer`

This keeps the integration name friendly while still showing the real hardware model on the device page.

## After setup

If setup succeeds, Home Assistant should create one ThermoPro device with grouped entities because the integration provides shared `device_info`, Bluetooth connections, and stable unique IDs for the entities.

### Typical TP902 result

- Probe 1
- Probe 2
- Units
- Alarm sound
- Probe 1 alarm
- Probe 1 Min
- Probe 1 Max
- Probe 2 alarm
- Probe 2 Min
- Probe 2 Max
- Battery

### Typical TP904 result

- Probe sensors for the TP904 model
- Units
- Alarm sound
- Battery

## Troubleshooting

| Problem | Meaning | What to check |
|---|---|---|
| `TP902 not currently visible via HA Bluetooth` | Home Assistant cannot currently see the thermometer in its Bluetooth discovery data. | Move the thermometer closer, verify Bluetooth is enabled, and make sure the device is advertising. |
| `No backend with an available connection slot...` | Home Assistant sees the thermometer but cannot currently open a BLE connection path to it. | Check Bluetooth adapter capacity, Bluetooth proxy availability, and whether another app is connected. |
| No entities appear after install | The integration may not be loaded correctly. | Verify folder path, file names, `manifest.json`, and restart Home Assistant. |
| Integration does not show in Add Integration | Config flow may be missing or invalid. | Confirm `config_flow.py` exists and `manifest.json` has `config_flow: true`. |
| TP904 probe values do not appear correctly | TP904 support is still experimental. | Confirm the selected model is correct and expect possible protocol differences until real-device testing is completed. |

## Notes

This integration is a custom component, so Home Assistant will show the standard warning that the integration has not been tested by Home Assistant. That warning is expected for custom integrations.

TP904 support is currently marked as experimental because the shared TP90X library clearly defines a TP904 model with two probes, but the temperature packet handling has not yet been verified on a real TP904 device.

For quieter logs, normal retry and connection-status messages can be logged at `debug` level while real parser or connection failures remain at `warning` or `exception`.

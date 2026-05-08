# TP902 Home Assistant Custom Integration

This custom integration adds support for the ThermoPro **TP902** Bluetooth thermometer in Home Assistant through a custom component placed in `custom_components/tp902/`.

It uses a Home Assistant config entry, Bluetooth support, and sensor entities for Probe 1, Probe 2, and Battery.

## TP902 protocol library

This integration uses the TP902 BLE protocol [library](https://github.com/petrkr/thermopro-tp902/blob/master/tp902/__init__.py) from the [`petrkr/thermopro-tp902`](https://github.com/petrkr/thermopro-tp902) project.

The protocol code is a single-file library with a transport abstraction, no external dependencies, and compatibility with both CPython and MicroPython. It provides the packet helpers, command codes, data classes, and parsing logic needed to talk to the TP902 thermometer.

## What this integration provides

After installation and setup, the integration creates one TP902 device in Home Assistant with these entities

- `Probe 1` — temperature sensor.
- `Probe 2` — temperature sensor.
- `Battery` — diagnostic battery sensor, optionally disabled by default using entity registry properties.

The integration uses Home Assistant's Bluetooth stack and a config flow, so the thermometer should be added from the UI rather than through the old `configuration.yaml` sensor platform style.[2]

## Folder contents

Place the integration in this path inside your Home Assistant config directory:

```text
config/
└── custom_components/
    └── tp902/
        ├── __init__.py
        ├── manifest.json
        ├── config_flow.py
        ├── sensor.py
        └── tp902_proto.py
```

The `tp902` folder is the custom integration itself; Home Assistant loads the integration from that directory based on the `manifest.json` file and the integration domain name.

## Installation

1. Copy the whole `tp902` folder into `config/custom_components/` in your Home Assistant installation so the final path is `config/custom_components/tp902/`.
2. Restart Home Assistant so it discovers the new custom integration and loads its manifest and config flow.

## Add the thermometer

Before adding the device, make sure the TP902 is powered on, close to a Bluetooth adapter or Bluetooth proxy that Home Assistant can use, and not currently connected to the ThermoPro mobile app, because Bluetooth connection availability affects whether Home Assistant can claim the device.

Then add it in Home Assistant:

1. Open **Settings → Devices & Services**.
2. Click **Add Integration**.
3. Search for **TP902**.
4. Enter the thermometer Bluetooth MAC address, for example `C4:45:1C:AA:36:51`.
5. Enter a friendly name such as `TP902`.
6. Finish the setup flow.

The config flow stores the MAC address as the integration's unique identifier, which is the recommended pattern for local Bluetooth devices in Home Assistant.

## Finding the MAC address

The TP902 advertises over Bluetooth and exposes the ThermoPro service UUID `1086fff0-3343-4817-8bb2-b32206336ce8`, so the MAC address can usually be found from the Home Assistant Bluetooth page, Bluetooth debug output, or a BLE scanner app while the thermometer is awake and advertising.

If the device appears in Home Assistant Bluetooth diagnostics, use the displayed address exactly as shown there.

## After setup

If setup succeeds, Home Assistant should create one ThermoPro TP902 device with grouped entities because the integration provides shared `device_info`, Bluetooth connections, and unique IDs for the entities.

Typical result:

- Probe 1
- Probe 2
- Battery

The battery entity may be disabled by default if `_attr_entity_registry_enabled_default = False` is used in the battery sensor class, which is appropriate for lower-priority diagnostic entities.

## Troubleshooting

| Problem | Meaning | What to check |
|---|---|---|
| `TP902 not currently visible via HA Bluetooth` | Home Assistant cannot currently see the thermometer in its Bluetooth discovery data.[2] | Move the thermometer closer, verify Bluetooth is enabled, and make sure the device is advertising. |
| `No backend with an available connection slot...` | Home Assistant sees the thermometer but cannot currently open a BLE connection path to it.[2] | Check Bluetooth adapter capacity, Bluetooth proxy availability, and whether another app is connected. |
| No entities appear after install | The integration may not be loaded correctly.[2] | Verify folder path, file names, `manifest.json`, and restart Home Assistant. |
| Integration does not show in Add Integration | Config flow may be missing or invalid.[2] | Confirm `config_flow.py` exists and `manifest.json` has `config_flow: true`. |

## Notes

This integration is a custom component, so Home Assistant will show the standard warning that the integration has not been tested by Home Assistant. That warning is expected for custom integrations and does not by itself indicate a functional problem.

For quieter logs, regular retry and connection-status messages can be logged at `debug` level while real parser or connection failures remain as `warning` or `exception`, which keeps normal BLE retries from spamming the main log.

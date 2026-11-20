# Changelog

## 1.1.0 — New integration id

- **Integration id renamed** from `philips_titanos_oled` to `philips_titanos_ambilight`. The Remote
  sees it as a new integration: remove the 1.0.0 integration, install this package, pair the TV
  again and put the entity back in your activities. No functional change.

## 1.0.0 — First release

Tested on a Philips 65OLED851 (Titan OS, JointSpace API 6). Integration id: `philips_titanos_oled`.

- **Pairing** with the PIN shown on the TV (JointSpace digest pairing, HTTPS with HTTP fallback).
- **Power state** read with one `notifychange` request kept open, like the Philips app, because
  `GET powerstate` always reports "On" on Titan OS. The entity follows the TV, including changes made
  with the Philips remote or HDMI-CEC.
- **ON/OFF** with the `Standby` key, sent only when the known state calls for it (the TV ignores
  `POST powerstate`), with Wake-on-LAN as a fallback. The Remote gets its answer immediately.
  - The TV may stay silent while it boots: the state targeted by the key is shown until it answers.
  - 15 s rest time between power changes: a later order is held until it ends, and pressing ON/OFF
    again cancels it. A second press within 2 s is ignored as a bounce.
- **Ambilight page**: video, audio, fixed colour and app modes, brightness and saturation, on/off, and
  a toggle that restores the last mode you chose.
- **Remote pages** for controls and media, in English or French. Every button is also a command for
  activities (`repeat`, `delay` and `hold` supported).
- Left out on purpose because the TV does not support them reliably: automatic HDMI input selection,
  picture mode, volume display and a media player entity (see the README).

Inspired by [daCream87/uc-philips-titanos](https://github.com/daCream87/uc-philips-titanos), the first
Titan OS integration for the Remote. This project's code is written from the public JointSpace
protocol and the ucapi-framework patterns, under the MIT license.

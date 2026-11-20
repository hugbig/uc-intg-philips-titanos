<p align="center">
  <img src="assets/titanos_entite.png" alt="Philips Titan OS integration icon" width="90" height="90">
</p>

<h1 align="center">Philips Titan OS TV for Unfolded Circle Remote 3</h1>

<p align="center">
  <a href="https://github.com/hugbig/uc-intg-philips-titanos/actions/workflows/tests.yml"><img src="https://github.com/hugbig/uc-intg-philips-titanos/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/hugbig/uc-intg-philips-titanos/actions/workflows/build.yml"><img src="https://github.com/hugbig/uc-intg-philips-titanos/actions/workflows/build.yml/badge.svg" alt="Build"></a>
  <a href="https://github.com/hugbig/uc-intg-philips-titanos/releases/latest"><img src="https://img.shields.io/github/v/release/hugbig/uc-intg-philips-titanos" alt="Latest release"></a>
  <a href="https://github.com/hugbig/uc-intg-philips-titanos/releases"><img src="https://img.shields.io/github/downloads/hugbig/uc-intg-philips-titanos/total" alt="Downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/hugbig/uc-intg-philips-titanos" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11-blue" alt="Python 3.11">
</p>

Control a Philips TV running **Titan OS** from an Unfolded Circle Remote 3, directly over the local
network (JointSpace API 6). There is no cloud service and no extra hub.

> **Unofficial community integration.** It is not affiliated with, endorsed by, or supported by
> Philips, TP Vision, Titan OS, or Unfolded Circle.

It was built from observations of a real TV and of the official Philips app. Its integration id is
`philips_titanos_ambilight`, so it can be installed alongside other Philips Titan OS integrations (such
as `philips_titanos`) without either one overwriting the other.

## What it does

- **Reliable power state.** On Titan OS, `GET powerstate` always reports "On". Instead, the
  integration keeps one `notifychange` request open, like the Philips app does, and the TV answers
  as soon as its state changes. The entity follows the TV even when you use the Philips remote.
- **ON/OFF in one press.** The TV ignores `POST powerstate`, so the integration sends the `Standby`
  key, which toggles power, and only when the known state calls for it. Wake-on-LAN is used as a
  fallback when the TV is in deep sleep or unreachable. The Remote gets its answer immediately, and
  the integration confirms power-on in the background.
- **Rest time between power changes.** The TV does not handle quick on/off sequences well. For
  15 s after a `Standby` key, a new power order is held until the rest time ends. Pressing ON/OFF
  again during that time cancels the held order.
- **Ambilight page.** All the modes of the TV:
  - video: AI, Standard, Sport, Cinema, Game;
  - audio: Lumina, Disco, Rhythm;
  - fixed colour and app;
  - brightness and saturation ±;
  - on / off, and a toggle that restores the last mode you chose.
- **Remote pages** for controls and media, in English or French depending on the language of the
  Remote at setup time.
- **Every button is also a command** you can use in activities, for example `AMBI_GAME`, `AMBI_OFF`,
  `OPTIONS` or `POWER_TOGGLE`. Commands support `repeat`, `delay` and `hold`.

### What it does not do, on purpose

These were tested on a 65OLED851 and left out because the TV does not support them reliably:

- **Automatic HDMI input selection.** The Sources menu takes about 10 s to open and the active input
  cannot be read. Use HDMI-CEC so the TV switches on to the right input, or use SOURCE and the arrow
  keys.
- **Picture mode.** It is not exposed by the API, and the TV stores it per input.
- **Volume display.** With an amplifier on ARC, the TV reports a fixed value. The volume and mute
  keys still control the amplifier.
- **Media player entity.** The TV reports no title, source or volume, so the screen stayed empty.
  Everything goes through the remote entity.

## Tested TV

- Philips 65OLED851 (Titan OS), JointSpace API 6, HTTPS with digest pairing.

Other Titan OS models (2024 and later) probably work too. Reports are welcome.

## Requirements

- An Unfolded Circle **Remote 3** (core API 0.22.0 or later). The Remote 2 has not been tested.
- The TV and the Remote on the **same local network**.
- A **fixed IP address** for the TV (a DHCP reservation on your router is enough). The integration
  stores the IP given during setup.
- To switch the TV on from deep standby: the TV's network wake-up option enabled in its network
  settings ("Wake on LAN" over Ethernet, or "Switch on with Wi-Fi" / WoWLAN over Wi-Fi; the exact
  label may vary), and the MAC address of the interface the TV actually uses.

## Installation

1. Download `uc-intg-philips_titanos_ambilight-<version>-aarch64.tar.gz` from the
   [latest release](../../releases/latest). Do not use GitHub's auto-generated "Source code"
   archives.
2. In the Remote's Web Configurator, open **Integrations**, add a new integration, and upload the
   archive.
3. Start the setup:
   1. Enter the IP address, MAC address (for Wake-on-LAN) and a name for the TV.
   2. Type the PIN shown on the TV.
4. Add the remote entity to your activities.

**Updating.** Remote firmware older than 2.9.3 cannot update a custom integration in place. You
must delete the integration, install the new archive, pair again and re-add the entity. Back up
your Remote configuration first, because activities that use the entity may need to be fixed
afterwards. On firmware 2.9.3 or later, use "Update existing driver" instead.

## Using the integration

The integration creates one **remote entity** per TV, with its own pages (controls, media,
Ambilight) and a mapping for the Remote's physical buttons. Every command below can also be used
in activities and macros, with `repeat`, `delay` and `hold`.

| Group | Commands |
|---|---|
| Power | `POWER_TOGGLE`, `POWER_ON`, `POWER_OFF` |
| Navigation | `CURSOR_UP`, `CURSOR_DOWN`, `CURSOR_LEFT`, `CURSOR_RIGHT`, `CURSOR_ENTER`, `BACK`, `HOME` |
| TV menus | `SETTINGS` (quick settings), `OPTIONS`, `INFO`, `SOURCE`, `TV_EXIT`, `CHANNELS_APP` |
| Volume | `VOLUME_UP`, `VOLUME_DOWN`, `MUTE` |
| Channels | `CHANNEL_UP`, `CHANNEL_DOWN` |
| Playback | `PLAY_PAUSE`, `PLAY`, `PAUSE`, `STOP`, `REWIND`, `FAST_FORWARD`, `PREVIOUS`, `NEXT`, `RECORD` |
| Ambilight modes | `AMBI_VIDEO_AI`, `AMBI_VIDEO_STD`, `AMBI_SPORT`, `AMBI_CINEMA`, `AMBI_GAME`, `AMBI_LUMINA`, `AMBI_DISCO`, `AMBI_RYTHM`, `AMBI_COLOR`, `AMBI_APP` |
| Ambilight settings | `AMBI_ON`, `AMBI_OFF`, `AMBILIGHT_TOGGLE` (restores the last mode), `AMBI_BRIGHT_UP`, `AMBI_BRIGHT_DOWN`, `AMBI_SAT_UP`, `AMBI_SAT_DOWN` |
| Other keys | `RED`, `GREEN`, `YELLOW`, `BLUE`, `DIGIT_0` to `DIGIT_9` (no effect on the 65OLED851) |

With `hold`, only the volume, arrow and channel keys repeat; the other keys are sent once.

**Recommended activity setup.** A physical button sends a command to **one** device. In an
activity that mixes the TV with a source device (Google TV, console):

- arrows, OK, Back, Home and playback go to the source device;
- volume and mute go to the TV, whose keys control the amplifier;
- a touch block on the activity screen holds the TV-only commands: SETTINGS, OPTIONS, SOURCE,
  Ambilight, and a small arrow pad for the TV menus.

**Pages and language.** Pages and button mappings are created when the entity is added to the
Remote. After an update that changes them, reset the entity's interface on the Remote. After
changing the Remote's language, run the device setup again to get pages in the new language.

## Troubleshooting

- **No PIN on the TV during setup.** The TV must be on (not in standby) and reachable at the IP
  you entered. Check that the Remote and the TV are on the same network.
- **The TV does not switch on from standby.** Check the network wake-up option and the MAC address
  (see [Requirements](#requirements)). Over Wi-Fi, the MAC is the one of the Wi-Fi interface, not
  the Ethernet one.
- **A second ON/OFF press is ignored.** A press within 2 s of the previous one is treated as a
  bounce. After a power change, the TV gets 15 s of rest: a new order is held until then, and
  pressing ON/OFF again cancels it.
- **The power state is late after a long standby.** While it boots, the TV can stay silent for
  about 30 s. The entity catches up as soon as the TV answers.
- **The first command after a pause is slow.** The TV takes about 2 s to accept the first request
  on a new connection. Later commands are fast.
- **A press made while the Remote was asleep did nothing.** The Remote may not send presses made
  while it is waking up from power saving. Press again.
- **Buttons or pages did not change after an update.** Reset the entity's interface on the Remote
  (see [Pages and language](#using-the-integration)).

## Support

- Bugs and feature requests: [GitHub Issues](../../issues). Please include the TV model, the Remote
  firmware version and the integration logs.
- Questions and discussion: the [Unfolded Circle community forum](https://unfolded.community).

## Development

You need Docker. First create a local `.env` file (not versioned) with your user id:

```bash
printf 'DEV_UID=%s\nDEV_GID=%s\n' "$(id -u)" "$(id -g)" > .env
docker compose -f compose.dev.yaml run --rm tests   # pytest
docker compose -f compose.dev.yaml run --rm lint    # ruff
```

The tests run against a fake JointSpace server, [tests/fake_tv.py](tests/fake_tv.py). It behaves
like the real 65OLED851, including the long-poll `notifychange`, the reporting delay after a
`Standby` key, and the HTTP 503 answers. It can also run on its own:
`docker compose -f compose.dev.yaml up fake-tv` (port 1925, PIN `1234`).

The dev Docker network uses `172.28.0.0/24`. If it overlaps an existing network ("Pool overlaps"),
pick a free range and add it to `.env`, for example `DEV_SUBNET_PREFIX=172.31.250`. The fake TV and
the driver then use `<prefix>.10` and `<prefix>.20`.

### Testing with the official Unfolded Circle simulator

```bash
mkdir -p .dev-config
docker compose -f compose.dev.yaml up -d core-simulator fake-tv driver
scripts/register_dev_driver.sh          # registers the driver (no mDNS) via POST /api/intg/drivers
```

Then, in the Web Configurator (<http://localhost:8080/configurator>, PIN `1234`), add the
"Philips Titan OS TV (dev)" integration with TV IP `172.28.0.10` and PIN `1234`. To watch the keys
the fake TV receives, run `docker compose -f compose.dev.yaml logs -f fake-tv`.

### Packages

GitHub Actions builds the aarch64 package with PyInstaller:

- on feature branches, it is a test artifact only;
- on `main`, it publishes a release when the version in `driver.json` is new.

### Exploring a new TV

`tools/titan_explore` is a guided session of about one hour. It measures what a TV really does:
- power state, wake-up, active input and CEC;
- keys, volume with an amplifier, Sources menu;
- Ambilight, picture mode, notifications;
- a comparison with the Philips Smart TV app;
- stability.

Run it from a Linux machine with Docker on the **same local network** as the TV, with the `.env`
file described above. The container uses the host network (for Wake-on-LAN) and opens no port.

```bash
docker compose -f compose.explore.yaml run --rm explore --host <TV IP> --mac <TV MAC>
```

- At least 2 s between requests. The session stops at the first sign that the TV's server is
  stuck.
- Settings it changes (Ambilight, picture mode) are restored, even after Ctrl+C.
- The stability test can freeze the TV's server. If that happens, unplug the TV for 30 seconds.
- Options:
  - `--list` lists the steps;
  - `--step N` runs a single step;
  - `--from-step N` resumes from a step;
  - `--interval` sets the delay between requests.
- Results go to `exploration/`, which is not versioned:
  - `report.md`: summary;
  - `journal.jsonl`: every request;
  - `credentials.json`: pairings, keep it private.

## Credits

- Inspired by [daCream87/uc-philips-titanos](https://github.com/daCream87/uc-philips-titanos), the first Titan OS
  integration for the Remote 3.
- The MQTT client and `titan_ca.crt` of the exploration tool come from
  [bedirhanyildirim/philips-titan-os-55pml9019-remote](https://github.com/bedirhanyildirim/philips-titan-os-55pml9019-remote)
  (MIT).
- Built with [ucapi](https://github.com/unfoldedcircle/integration-python-library) and
  `ucapi-framework`, following the [Unfolded Circle Core API](https://github.com/unfoldedcircle/core-api).

See [CHANGELOG.md](CHANGELOG.md) for the version history.

## License

MIT, see [LICENSE](LICENSE). Third-party parts are listed in [NOTICE](NOTICE).

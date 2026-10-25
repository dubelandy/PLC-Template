# OPC UA dashboard

A small web page that shows the example machine live over OPC UA (TwinCAT TF6100) and lets you start/stop it and drive the software simulator.

## Setup (once)

1. Install Python 3.10 or newer from python.org (tick **Add python.exe to PATH**).
2. In this folder, open a command prompt and run:
   ```
   pip install -r requirements.txt
   ```

## Run

1. Activate ExampleProject and make sure the PLC is running.
2. In this folder:
   ```
   python app.py
   ```
3. Enter the OPC UA login when asked: the Windows user name and password you used to initialize the TF6100 server. Leave the user blank for anonymous.
4. Open http://localhost:8080.

To skip the prompt, set `OPCUA_USER` and `OPCUA_PASSWORD` in the command prompt before running (`set OPCUA_USER=...`). The password is never saved to disk.

## First connection: trust the dashboard's certificate

The connection is encrypted (`Basic256Sha256,SignAndEncrypt`). On first run the dashboard creates its own certificate in `pki/` (git-ignored). If the server rejects it (`BadSecurityChecksFailed` or `BadCertificateUntrusted` in the console):

1. Open the **TwinCAT OPC UA Configurator**, connect to the server.
2. Go to the certificate / security section, find the **rejected** certificate named *PLC-Template Dashboard*, and move it to **trusted**.
3. The dashboard retries every 3 s on its own.

## What it shows

| Panel | Contents |
|---|---|
| Machine | State, mode, ready/faulted; Start, Stop, Reset buttons (`MAIN.machine.ocmd`) |
| Example station | Run step, current job, cycles, last cycle time, rejected jobs and reason, comm error |
| Actuators | Position (open/closed/moving), mode, fault text |
| Trigger / tell | Transaction state, the five handshake bits as lamps, request and response |
| Software simulator | Step and counters, last response; enable, freeze, invalid request and closeDwell controls |

Variables the server doesn't publish are listed at the bottom of the page. Add `{attribute 'OPC.UA.DA' := '1'}` to them (and each parent) and activate again.

## Settings (`config.json`)

| Key | Default | Meaning |
|---|---|---|
| `endpoint` | `opc.tcp://localhost:4840` | TF6100 server address |
| `security` | `Basic256Sha256,SignAndEncrypt` | Security policy and mode; `None` if the server allows unsecured connections |
| `plcRoot` | `PLC1` | Name of the PLC node under Objects on the server |
| `pollIntervalMs` | `250` | How often values are read |
| `httpPort` | `8080` | Port of the web page |

The page only listens on `localhost`, and only the variables listed in `WRITABLE` in `app.py` can be written.

## Adding a value

1. Add its path (below the PLC node, e.g. `MAIN.machine.exampleStation.stsStation.cycleCount`) to `TAGS` in `app.py`.
2. Show it in `index.html` with `v("…path…")`.

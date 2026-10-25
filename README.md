# PLC-Template

A TwinCAT 3 template made of two parts:

- **MachineLibrary**: a reusable PLC library of machine building blocks (devices, modules, permissives, sequencer functions).
- **ExampleProject**: a small machine built on MachineLibrary, meant to be copied as a starting point.

## Layout

```
PLC Template.sln                 Opens both projects
MachineLibrary/
  MachineLibrary.tsproj
  MachineLibrary/                PLC library project (namespace MachineLibrary)
    _General/                    Shared types, enums and constants
    Devices/                     Device, Actuator, AnalogActuator, DigitalInput, Motor (Axis, VFD)
    Module/                      FB_Module: Start/Stop state machine for machines and stations
    Process/                     Permissive, ParentChildControl, Sequencer, TriggerTell
    Utility/                     RTO (retentive timer)
ExampleProject/
  ExampleProject.tsproj
  ExamplePLC/                    PLC application, references MachineLibrary
    POUs/                        MAIN, FB_Machine
    Stations/ExampleStation/     FB_ExampleStation (two actuators)
    Communication/MQTT/          FB_MqttStatePublisher
.claude/skills/                  Style guide for writing new MachineLibrary code
Tools/OPCUA-Dashboard/           Web dashboard over OPC UA (TF6100) for the example machine
```

## Getting started

1. Open `PLC Template.sln` in TwinCAT XAE (4024 or newer).
2. Install the library: right-click the **MachineLibrary** PLC project, choose **Save as library and install**.
3. Build **ExampleProject**. It references `MachineLibrary, * (PLC-Template)`, so it always uses the newest installed version.
4. Make sure **ExampleProject** is the active project (right-click it → **Set as StartUp Project**), then activate and log in.

Only activate ExampleProject. MachineLibrary is a library and has nothing to run.

Both projects run real-time on an isolated core (core 19 of 20, set in each `.tsproj` under SYSTEM → Real-Time). If your PC has a different core count, change it there before activating. Never run real-time on a core shared with Windows on a laptop: it can crash the PC.

After changing the library, bump `ProjectVersion` in the library properties and install it again.

## The example machine

`MAIN` calls `machine : FB_Machine`, which owns one station, `exampleStation : FB_ExampleStation`, with two `FB_Actuator2State` instances (home = open, work = closed).

| Machine command (`machine.ocmd`) | What happens |
|---|---|
| `Start` | Station homes: both actuators open. Then it runs: close both, open both, dwell, repeat. |
| `Stop` | Station opens both actuators, then stops. |
| `Reset` | Resets actuator faults. |

While stopped, the actuators are in Manual and accept operator commands (`machine.exampleStation.actuatorA.ocmd`). A faulted actuator stops the station, and a faulted station stops the machine.

The actuators are configured without feedback, so the example runs with no I/O. To use real hardware, clear `homeNoFdbk`/`workNoFdbk` in `FB_ExampleStation` and link `homeFdbk.inpSignal`, `workFdbk.inpSignal`, `outHome` and `outWork` in the I/O tree.

### Trigger/tell test

Each running cycle of the station is one `FB_TriggerTell` transaction (`FB_ExampleTransaction`). `MAIN.softwareSim` plays the software side, so it runs with no outside software.

1. Start the machine (`MAIN.machine.ocmd := Start`).
2. Watch `MAIN.machine.exampleStation.stsStation.runStep` go RequestJob → WaitJob → WaitWorking → Close → HoldClosed → Open → Report → WaitReportAck → Dwell, and `transaction.sts.state` / `transaction.handshake` step through the handshake.
3. `MAIN.softwareSim.sts.lastResponse` shows what the station reported (cycleId, cycleTime, ok).

| Test | Set | Expect |
|---|---|---|
| Comm timeout | `softwareSim.cfg.freeze := TRUE` | After `commTimeout` (10 s), `stsStation.commError` and `transaction.sts.errTimeout` turn on. Clear `freeze` and the cycle continues. |
| Rejected request | `softwareSim.cfg.sendInvalidRequest := TRUE` | Station aborts the transaction, `stsStation.jobsRejected` counts up, `lastRejectText` says why, `softwareSim.sts.aborts` counts up. |
| Recipe value | `softwareSim.cfg.closeDwell := T#5S` | Actuators stay closed 5 s per cycle, `lastResponse.cycleTime` grows. |
| Stop mid-transaction | `machine.ocmd := Stop` | Transaction aborted, actuators open, simulator resets to Idle. |

### OPC UA dashboard

`Tools/OPCUA-Dashboard` is a small Python web page that shows all of the above live over OPC UA (needs TwinCAT TF6100) and can start/stop the machine and drive the simulator. See its README.

### MQTT

`FB_MqttStatePublisher` publishes `{"state":"Started","cycleCount":12}` to `plc-template/example/state` on `broker.hivemq.com` (a public test broker) on every state change and every 10 s. Settings live in `machine.cfgMqtt`.

Remote `START`/`STOP`/`RESET` commands on `plc-template/example/cmd` are **off by default** (`enableRemoteCommands`), because anyone can publish to a public broker. Point `hostName` at your own broker before turning them on.

## Library overview

| Area | Blocks |
|---|---|
| Devices | `FB_Device` (base: Auto/Manual, override, bypass, sim, parent control), `FB_Actuator2State`, `FB_ActuatorAnalog`, `FB_DigitalInput`, `FB_Axis` (NC axis), `FB_VFD` (CiA402 / Schneider IO) |
| Module | `FB_Module` (abstract Stopped/Starting/Started/Stopping state machine, passes mode to children through `childCtrl`) |
| Process | `FB_Permissive` (16-bit permissive/interlock with bypass), `FB_SequencerFunction` (start/complete/timeout wrapper around a device action), `FB_TriggerTell` (handshake), `ST_ParentChildControl` |
| Utility | `RTO` retentive timer |

Library dependencies: Tc2_Standard, Tc2_System, Tc2_Utilities, Tc2_MC2, Tc2_MC2_Drive.

## Writing new code

Follow the style guide in `.claude/skills/machinelibrary-style/SKILL.md`. It covers naming, the `cfg`/`ctrl`/`sts`/`fault`/`func` interface, the standard method call order, and templates for a new device and a new module.

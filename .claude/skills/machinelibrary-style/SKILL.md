---
name: machinelibrary-style
description: Style guide for TwinCAT 3 Structured Text in this repo's MachineLibrary and example projects. Use when writing, reviewing or refactoring any function block, DUT, enum or GVL here — new devices, modules, stations, or edits to existing ones.
---

# MachineLibrary style guide

Code in `MachineLibrary/` is a reusable TwinCAT 3 library (namespace `MachineLibrary`). Code in `ExampleProject/` is a machine built on it. New code must look like it was written by the same person as `FB_Actuator2State`, `FB_Device` and `FB_Module`. When in doubt, open one of those and copy its shape.

## Where code goes

- **Library**: generic, machine-independent blocks (a device type, a process helper, a utility). No hard-coded I/O, hostnames, paths or recipes.
- **Example / application**: machine-specific modules and stations, communication setup, anything that names a real piece of equipment.
- A block that only one machine uses stays in the application until a second machine needs it.

## Naming

| Thing | Pattern | Example |
|---|---|---|
| Function block | `FB_` + PascalCase | `FB_Actuator2State`, `FB_ExampleStation` |
| Interface | `I_` | `I_SpeedController` |
| Struct | `ST_` | `ST_Actuator2StateStatus` |
| Enum | `E_` | `E_ActuatorCommand` |
| Alias | `T_` | `T_DeviceNameString` |
| Library GVL | `GVL_Lib_<Area>Constants` | `GVL_Lib_SequencerConstants` |
| Constants | `UPPER_SNAKE` | `MAX_PARAMETERS`, `ALL_TRUE_INT` |
| Variables, methods' locals | lowerCamelCase, no Hungarian prefixes | `homeTimer`, `cmdExecuting` |
| Methods | PascalCase verbs | `ToHome`, `ProcessCommands` |

Each device or module `X` gets a matching set of types (only the ones it needs):

`ST_XConfiguration` (cfg) · `ST_XStatus` (sts, devices `EXTENDS ST_DeviceStatus`) · `ST_XFault` (fault) · `ST_XFunctions` (func) · `E_XCommand` · `E_XState` · `E_XFunctionParam`

Standard abbreviations, used consistently:

| Abbrev | Meaning | Abbrev | Meaning |
|---|---|---|---|
| `cfg` | configuration | `sts` | status |
| `ctrl` | HMI control bits | `func` | sequencer functions |
| `ocmd` | operator command (HMI, Manual only) | `pcmd` | program command (code, Auto only) |
| `Intlk` | interlock: stops/prevents motion | `Perm` | permissive: required to start |
| `Fdbk` | feedback | `Ovrde` | override |
| `rt` / `ft` | rising / falling trigger | `inp` / `out` | external input / output |
| `echo` | copy of a signal for the HMI | `Prv` | private command handler (`PrvHome`) |

## Folder layout

One folder per block, with subfolders for its types:

```
Devices/Actuator/
  FB_Actuator2State.TcPOU
  _DUTs/   ST_Actuator2StateConfiguration, ...Status, ...Fault, ...Functions
  _ENUMs/  E_ActuatorCommand, E_ActuatorState
  _GVLs/   (constants, if any)
```

Library top level: `_General`, `Devices`, `Module`, `Process`, `Utility`. Application: `POUs`, `Stations/<Name>`, `Communication/<Protocol>`.

## Declarations

Order inside a function block:

```
FUNCTION_BLOCK FB_X EXTENDS FB_Device
(*
	What it does, in a few lines. Mention position meanings (e.g. home = open) and sim behavior.
*)
VAR_INPUT
	cfg, ocmd, func
	(* Interlocks/Permissives *)   xIntlk / xPerm : FB_Permissive
	(* External inputs *)          inpX AT %I*
END_VAR
VAR_OUTPUT
	outX AT %Q*
	sts, fault
END_VAR
VAR
	//Command processing   pcmd, pcmdLast, ocmdLast, cmdReceived, cmdExecuting
	//state variables      stateLast, stateLastScan
	//Oneshot triggers     rtNewState
	//Timers               workTimer : TON := (PT := T#5M);
END_VAR
```

- Every variable gets a short `//` comment after it. Align with tabs.
- Section headers inside declarations use:
  ```
  (* Interlocks/Permissives
  ----------------------------------------------------------------------------------------------------*)
  ```
- **OPC UA**: anything the HMI reads or writes gets `{attribute 'OPC.UA.DA' := '1'}`. Add `{attribute 'OPC.UA.DA.StructuredType' := '1'}` for structs/FBs, and `{attribute 'OPC.UA.DA.Access' := '1'}` when it is read-only (`sts`, `fault`, permissives).
- **Enums** always have `{attribute 'qualified_only'}`, `{attribute 'strict'}`, `{attribute 'to_string'}`, explicit values, and a comment per value. Command enums start with `None := 0`.
- Status structs of devices `EXTENDS ST_DeviceStatus`. Modules keep their own status in `stsX` because `FB_Module` already owns `sts`.
- Don't name a type the same as one in a referenced Beckhoff library (e.g. `ST_AxisStatus` exists in Tc2_MC2, so ours is `ST_AxisDeviceStatus`).

## Devices (`EXTENDS FB_Device`)

The body is a fixed list of protected method calls, always in this order (skip ones a device doesn't need, never reorder):

```
SUPER^();          // FB_Device: mode (Auto/Manual), manual override timeout, triggers

Device();          // map cfg -> FB_Device, FB_Device -> sts. Must come right after SUPER^()
StatusIn();        // call interlocks/permissives: xIntlk(bypActive := sts.bypass, cfg := cfg.xIntlk)
ProcessInputs();   // feedback, debounce, simulation timers
ProcessCommands(); // accept ocmd in Manual / pcmd in Auto, check interlocks, clear commands
Functions();       // sequencer functions (func.X)
StateMachine();    // CASE sts.state, monitoring timers, rtNewState
HandleFaults();    // set, reset, map id and text
ControlOutputs();  // physical outputs, all FALSE when ctrl.sim
StatusOut();       // derived status flags, echo bits
```

Rules:

- **Commands**: public methods (`ToHome()`, `Stop()`) only set `pcmd`. `ProcessCommands` accepts `ocmd` only in Manual and `pcmd` only in Auto; otherwise it sets `fault.ocmdNOK` / `fault.pcmdNOK`. Both are cleared at the end of every scan. Validation lives in `Prv<Command>` methods.
- **Interlocks vs permissives**: losing an interlock during motion triggers `PrvSafe()`; a permissive is only checked when a command starts.
- **Simulation**: every device supports `ctrl.sim`. Outputs are forced off and feedback comes from timers (`cfg.homeNoFdbkTime`). The same timers cover devices configured without feedback.
- **Mode**: never compute Auto/Manual yourself. `FB_Device` derives it from `ctrl.manualOvrde` and `parentCtrl.mode`. Callers pass `parentCtrl := childCtrl`.

## Faults

`ST_XFault` has `active : BOOL`, `id : UDINT`, `text : T_MaxString`, then one BOOL per fault grouped under section headers (motion, programming, ...). `HandleFaults` always has four blocks:

1. Set faults with `S=` (or note where they are set elsewhere).
2. `(* ----- Handle Reset ----- *)` reset every fault with `R=` when `resetFault`.
3. `(* ----- Map Fault Id ----- *)` one bit per fault, alphabetical.
4. `(* ----- Map Fault Text ----- *)` an `IF/ELSIF` chain in the same order, then `fault.active := fault.id > 0;`.

## Permissives

Use `FB_Permissive` for every interlock, permissive and completion condition. Set one bit per condition every scan and describe it:

```
PermStartComplete.cfg.condText[0] := 'Actuator A open';
PermStartComplete.perm.0 := actuatorA.sts.atHome;
```

Unused bits default to TRUE (`GVL_Lib_GeneralConstants.ALL_TRUE_INT`). Mark bypassable bits in `cfg.bypassable`.

## Sequencer functions

Expose actions a sequencer can call as `FB_SequencerFunction` members of `ST_XFunctions`. In `Functions()`:

```
func.ToHome(hmiTextStatic := CONCAT(cfg.actuatorId, ' to home'), timeoutPT := T#30S);
func.ToHome.permComplete.cfg.condText[0] := CONCAT(cfg.actuatorId, ' at home');
func.ToHome.permComplete.perm.0 := sts.atHome;   // bit 0 is cleared on every start

IF func.ToHome.entry THEN       // read arrParam here
	ToHome();
END_IF
IF func.ToHome.running THEN
	func.ToHome.inpError := fault.active;
	func.ToHome.inpErrorText := fault.text;
END_IF
```

Parameters come in through `arrParam[i].typeEnum` (compare with `E_XFunctionParam`) and `arrParam[i].value` (LREAL), looping `GVL_Lib_SequencerConstants.MIN_PARAMETERS TO MAX_PARAMETERS`.

## Modules and stations (`EXTENDS FB_Module`)

```
SUPER^();          // FB_Module: commands, state machine, mode, calls Starting/Started/Stopping

Devices();         // actuatorA(parentCtrl := childCtrl); inpChildFaulted := ...fault.active
Permissives();     // PermStartComplete, PermStopComplete, IntlkAuto bits
StatusOut();       // stsX flags and timers
```

- Override `Starting()` (homing), `Started()` (running sequence), `Stopping()` (go to safe position) and `Reset()`. Keep signatures identical to `FB_Module` (`METHOD PROTECTED Started : BOOL`, `METHOD Reset : BOOL`).
- Running sequences are a `CASE` over an `E_XRunStep` enum with steps numbered 10, 20, 30.
- Issue a device command only if it isn't already there or moving there: `IF NOT a.sts.atHome AND NOT a.sts.goingToHome THEN a.ToHome(); END_IF`.
- Parent modules command child modules with `child.pcmd := E_ModuleCommand.Start` in `Starting()` and finish when `PermStartComplete` sees `child.sts.Started`.
- A faulted child should drop `IntlkAuto` so the module stops itself.

## Implementation style

- Tabs for indentation; align `:=` in blocks of related assignments.
- One responsibility per method; the body only calls methods.
- Comments explain *why* or the rule being enforced, not the syntax.
- No magic numbers in logic: put them in `cfg` with a default, or in a `GVL_Lib_*Constants`.
- No hard-coded paths, hostnames, credentials or user names in library code; in the example they go in a `cfg` struct with a comment.
- Delete experiments, test variables and commented-out code before committing.

## Editing files outside TwinCAT

- New files must be added to the project's `.plcproj` (`<Compile Include="...">` plus `<Folder Include="...">` for new folders), with backslash paths.
- Every new object needs a fresh GUID in `Id="{...}"`. Object `Name`, file name and the name in the declaration must match.
- Stale `<LineIds>` blocks can be deleted; TwinCAT regenerates them.
- After changing the library, bump `ProjectVersion` in `MachineLibrary.plcproj` and reinstall it.

## Templates

Copy-ready code for a new device and a new station: `references/templates.md`.

## Review checklist

- [ ] Names, abbreviations and folder layout follow the tables above
- [ ] Every variable commented; OPC UA attributes on HMI variables
- [ ] Enums are qualified_only/strict/to_string with `None := 0` for commands
- [ ] Device body uses the standard call order with `Device()` right after `SUPER^()`
- [ ] Commands go through `pcmd`/`ocmd` and are cleared every scan
- [ ] Sim mode forces outputs off and simulates feedback
- [ ] Faults have id bits and text in matching order; `active := id > 0`
- [ ] Permissive bits have `condText`
- [ ] No machine-specific values in library code
- [ ] Files listed in the `.plcproj`

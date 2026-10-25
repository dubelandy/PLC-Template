# Templates

Copy-ready code that follows the style guide. Both templates pass the repo's static checks against MachineLibrary.
In TwinCAT, create the objects with the same names, add the method folders (`Public\Commands`, `Public\Control`, `Protected\Logic`, `Protected\Commands`, `Protected\States`), put each method in the folder shown next to its name, then rename `TemplateDevice` / `TemplateStation`.

## Device: `FB_TemplateDevice`

One output that starts something, one run feedback, run interlock and permissive, start/stop timeouts, simulation.

### Types

`E_TemplateDeviceCommand` in `_ENUMs/`

```iecst
{attribute 'qualified_only'}
{attribute 'strict'}
{attribute 'to_string'}
TYPE E_TemplateDeviceCommand :
(
	None	:= 0, //no command
	Start	:= 1, //start the device
	Stop	:= 2 //stop the device
);
END_TYPE
```

`E_TemplateDeviceState` in `_ENUMs/`

```iecst
{attribute 'qualified_only'}
{attribute 'strict'}
{attribute 'to_string'}
TYPE E_TemplateDeviceState :
(
	Stopped		:= 0, //output off, no run feedback
	Starting	:= 1, //output on, waiting for run feedback
	Running		:= 2, //output on, run feedback on
	Stopping	:= 3 //output off, waiting for run feedback to drop
);
END_TYPE
```

`ST_TemplateDeviceConfiguration` in `_DUTs/`

```iecst
TYPE ST_TemplateDeviceConfiguration :
STRUCT
	deviceId			: T_DeviceNameString; //device id shown in texts
	
	//Feedback configuration
	runFdbk				: ST_DigitalInputConfiguration; //run feedback configuration
	noFdbk				: BOOL; //device has no run feedback
	noFdbkTime			: TIME := T#2S; //simulation or no feedback start/stop delay
	
	//Permissive/interlock configuration
	runIntlk			: ST_PermissiveConfiguration;
	runPerm				: ST_PermissiveConfiguration;
	
	//Configure monitoring timers
	failTimeStart		: TIME := T#5S; //start timeout
	failTimeStop		: TIME := T#5S; //stop timeout
	opTimeout			: TIME := T#300S; //how long operator override stays on without commands
	opTimeoutEnable		: BOOL := TRUE;
END_STRUCT
END_TYPE
```

`ST_TemplateDeviceStatus` in `_DUTs/`

```iecst
TYPE ST_TemplateDeviceStatus EXTENDS ST_DeviceStatus :
STRUCT
	state				: E_TemplateDeviceState := E_TemplateDeviceState.Stopped; //device state
	stopped				: BOOL; //stopped
	starting			: BOOL; //starting
	running				: BOOL; //running
	stopping			: BOOL; //stopping
	
	readyToStart		: BOOL; //run interlocks and permissives are good
	echoRunFdbk			: BOOL; //processed run feedback for HMI
	echoRunOut			: BOOL; //run output for HMI
END_STRUCT
END_TYPE
```

`ST_TemplateDeviceFault` in `_DUTs/`

```iecst
TYPE ST_TemplateDeviceFault :
STRUCT
	(* General error info
	----------------------------------------------------------------------------------------------------*)
	active				: BOOL;
	id					: UDINT;
	text				: T_MaxString;
	
	(* Motion error
	----------------------------------------------------------------------------------------------------*)
	startTimeout		: BOOL; //run feedback did not come on in time
	stopTimeout			: BOOL; //run feedback did not drop in time
	
	(* Programming error
	----------------------------------------------------------------------------------------------------*)
	runIntlkNOK			: BOOL; //run interlocks not OK
	runPermNOK			: BOOL; //run permissives not OK
	ocmdNOK				: BOOL; //operator command in Auto is not allowed
	pcmdNOK				: BOOL; //program command in Manual is not allowed
END_STRUCT
END_TYPE
```

### Function block

Declaration and body:

```iecst
FUNCTION_BLOCK FB_TemplateDevice EXTENDS FB_Device
(*
	Template device: one output that starts something, one run feedback.
	Copy, rename "TemplateDevice", and change states/commands to fit.
	Simulated or no-feedback devices use noFdbkTime to fake the feedback.
*)
VAR_INPUT
	{attribute 'OPC.UA.DA' := '1'}
	{attribute 'OPC.UA.DA.StructuredType' := '1'}
	cfg					: ST_TemplateDeviceConfiguration; //configuration
	
	{attribute 'OPC.UA.DA' := '1'}
	ocmd				: E_TemplateDeviceCommand; //operator command
	
	(* Interlocks/Permissives
	----------------------------------------------------------------------------------------------------*)
	{attribute 'OPC.UA.DA' := '1'}
	{attribute 'OPC.UA.DA.Access' := '1'}
	{attribute 'OPC.UA.DA.StructuredType' := '1'}
	runIntlk			: FB_Permissive; //interlocks that stop/prevent running
	{attribute 'OPC.UA.DA' := '1'}
	{attribute 'OPC.UA.DA.Access' := '1'}
	{attribute 'OPC.UA.DA.StructuredType' := '1'}
	runPerm				: FB_Permissive; //permissives required to start
	
	(* External inputs
	----------------------------------------------------------------------------------------------------*)
	runFdbk				: FB_DigitalInput; //run feedback, link runFdbk.inpSignal
END_VAR
VAR_OUTPUT
	outRun		AT %Q*	: BOOL; //physical run output
	
	{attribute 'OPC.UA.DA' := '1'}
	{attribute 'OPC.UA.DA.Access' := '1'}
	{attribute 'OPC.UA.DA.StructuredType' := '1'}
	sts					: ST_TemplateDeviceStatus;
	
	{attribute 'OPC.UA.DA' := '1'}
	{attribute 'OPC.UA.DA.Access' := '1'}
	{attribute 'OPC.UA.DA.StructuredType' := '1'}
	fault				: ST_TemplateDeviceFault;
END_VAR
VAR
	//Command processing
	pcmd				: E_TemplateDeviceCommand; //program command
	pcmdLast			: E_TemplateDeviceCommand;
	ocmdLast			: E_TemplateDeviceCommand;
	cmdReceived			: E_TemplateDeviceCommand; //command accepted this scan
	
	//state variables for tracking
	stateLastScan		: E_TemplateDeviceState; //state on last scan
	runFdbkProcessed	: BOOL; //processed run feedback
	
	//Oneshot triggers
	rtNewState			: BOOL; //just entered new state
	
	//Timers
	startTimer			: TON := (PT := T#5M);
	stopTimer			: TON := (PT := T#5M);
	
	resetFault			: BOOL;
END_VAR

SUPER^();

Device();
StatusIn();
ProcessInputs();
ProcessCommands();
StateMachine();
HandleFaults();
ControlOutputs();
StatusOut();
```

`ControlOutputs` in `Protected\Logic`

```iecst
METHOD PROTECTED ControlOutputs //Set physical outputs
IF sts.sim THEN //do not command outputs when simulated
	outRun := FALSE;
ELSE
	outRun := sts.state = E_TemplateDeviceState.Starting OR sts.state = E_TemplateDeviceState.Running;
END_IF
```

`Device` in `Protected\Logic`

```iecst
METHOD PROTECTED Device //map cfg to FB_Device and FB_Device to sts
// to FB device
opTimeout  			 := cfg.opTimeout;
opTimeoutEnable 	 := cfg.opTimeoutEnable;
opActivity 			 := ocmd <> E_TemplateDeviceCommand.None;

// from FB device
sts.mode	   		 := mode;
sts.modeAuto   		 := sts.mode = E_SystemMode.Auto;
sts.modeManual 		 := sts.mode = E_SystemMode.Manual;
sts.manualOvrde		 := ctrl.manualOvrde;
sts.bypass 	   		 := ctrl.bypass;
sts.sim		   		 := ctrl.sim;
sts.parentConfigured := parentConfigured;
```

`HandleFaults` in `Protected\Logic`

```iecst
METHOD PROTECTED HandleFaults
fault.startTimeout S= sts.starting AND startTimer.ET >= cfg.failTimeStart;
fault.stopTimeout S= sts.stopping AND stopTimer.ET >= cfg.failTimeStop;
//fault.runIntlkNOK; // Set in ProcessCommands and PrvStart
//fault.runPermNOK; // Set in PrvStart
//fault.ocmdNOK; // Set in ProcessCommands
//fault.pcmdNOK; // Set in ProcessCommands

(* ----- Handle Reset ----- *)
IF resetFault THEN
	fault.ocmdNOK R= TRUE;
	fault.pcmdNOK R= TRUE;
	fault.runIntlkNOK R= TRUE;
	fault.runPermNOK R= TRUE;
	fault.startTimeout R= TRUE;
	fault.stopTimeout R= TRUE;
END_IF
resetFault := FALSE;

(* ----- Map Fault Id ----- *)
fault.id.0 := fault.ocmdNOK;
fault.id.1 := fault.pcmdNOK;
fault.id.2 := fault.runIntlkNOK;
fault.id.3 := fault.runPermNOK;
fault.id.4 := fault.startTimeout;
fault.id.5 := fault.stopTimeout;

(* ----- Map Fault Text ----- *)
IF fault.ocmdNOK THEN			fault.text := 'Operator command in Auto is not allowed';
ELSIF fault.pcmdNOK THEN		fault.text := 'Program command in Manual is not allowed';
ELSIF fault.runIntlkNOK THEN	fault.text := 'Run interlocks not OK';
ELSIF fault.runPermNOK THEN		fault.text := 'Run permissives not OK';
ELSIF fault.startTimeout THEN	fault.text := 'Start timeout';
ELSIF fault.stopTimeout THEN	fault.text := 'Stop timeout';
ELSE fault.text := '';
END_IF

(* ----- Set Active ----- *)
fault.active := fault.id > 0;
```

`ProcessCommands` in `Protected\Logic`

```iecst
METHOD PROTECTED ProcessCommands
//Check for new valid commands
IF ctrl.reset THEN
	PrvReset();
ELSIF ocmd <> E_TemplateDeviceCommand.None THEN
	IF sts.modeManual THEN
		cmdReceived := ocmd;
	ELSE
		fault.ocmdNOK := TRUE;
	END_IF
ELSIF pcmd <> E_TemplateDeviceCommand.None THEN
	IF sts.modeAuto THEN
		cmdReceived := pcmd;
	ELSE
		fault.pcmdNOK := TRUE;
	END_IF
END_IF

//Losing interlocks while running stops the device
IF (sts.starting OR sts.running) AND NOT runIntlk.sts.ok THEN
	fault.runIntlkNOK S= TRUE;
	PrvStop();
END_IF

CASE cmdReceived OF
	E_TemplateDeviceCommand.Start:
		PrvStart();
	E_TemplateDeviceCommand.Stop:
		PrvStop();
END_CASE

//Save last commands
IF pcmd <> E_TemplateDeviceCommand.None THEN
	pcmdLast := pcmd;
END_IF
IF ocmd <> E_TemplateDeviceCommand.None THEN
	ocmdLast := ocmd;
END_IF

//Clear commands every scan
cmdReceived	:= E_TemplateDeviceCommand.None;
pcmd		:= E_TemplateDeviceCommand.None;
ocmd		:= E_TemplateDeviceCommand.None;
ctrl.reset	:= FALSE;
```

`ProcessInputs` in `Protected\Logic`

```iecst
METHOD PROTECTED ProcessInputs
//Call input FBs
runFdbk(cfg := cfg.runFdbk);

//Use simulation timers when simulated or without feedback
IF cfg.noFdbk OR sts.sim THEN
	IF sts.starting THEN
		runFdbkProcessed := startTimer.ET >= cfg.noFdbkTime;
	ELSIF sts.stopping THEN
		runFdbkProcessed := stopTimer.ET < cfg.noFdbkTime;
	END_IF
ELSE
	runFdbkProcessed := runFdbk.sts.debouncedSignal;
END_IF
```

`PrvReset` in `Protected\Commands`

```iecst
METHOD PROTECTED PrvReset //Reset the device
resetFault S= TRUE;

//Reset permissives/interlocks
runIntlk.Reset();
runPerm.Reset();
```

`PrvStart` in `Protected\Commands`

```iecst
METHOD PROTECTED PrvStart
IF NOT (sts.running OR sts.starting) THEN // ignore command if already running
	IF NOT runIntlk.sts.ok THEN
		fault.runIntlkNOK S= TRUE;
	ELSIF NOT runPerm.sts.ok THEN
		fault.runPermNOK S= TRUE;
	ELSE
		sts.state := E_TemplateDeviceState.Starting;
	END_IF
END_IF
```

`PrvStop` in `Protected\Commands`

```iecst
METHOD PROTECTED PrvStop
IF sts.running OR sts.starting THEN // stop has no permissives
	sts.state := E_TemplateDeviceState.Stopping;
END_IF
```

`Start` in `Public\Commands`

```iecst
METHOD PUBLIC Start
pcmd := E_TemplateDeviceCommand.Start;
```

`StateMachine` in `Protected\Logic`

```iecst
METHOD PROTECTED StateMachine
CASE sts.state OF
	
	E_TemplateDeviceState.Stopped:
		;
		
	E_TemplateDeviceState.Starting:
		IF runFdbkProcessed THEN
			sts.state := E_TemplateDeviceState.Running;
		END_IF
		
	E_TemplateDeviceState.Running:
		// If we got here based on a successful start (the only way to get here), reset faults
		IF rtNewState THEN
			resetFault := TRUE;
		END_IF
		
	E_TemplateDeviceState.Stopping:
		IF NOT runFdbkProcessed THEN
			sts.state := E_TemplateDeviceState.Stopped;
		END_IF
		
END_CASE

rtNewState := sts.state <> stateLastScan;
stateLastScan := sts.state;

// Monitoring timers
startTimer(IN := sts.state = E_TemplateDeviceState.Starting);
stopTimer(IN := sts.state = E_TemplateDeviceState.Stopping);
```

`StatusIn` in `Protected\Logic`

```iecst
METHOD PROTECTED StatusIn
//Permissives and Interlocks
runIntlk(bypActive := sts.bypass, cfg := cfg.runIntlk);
runPerm(bypActive := sts.bypass, cfg := cfg.runPerm);
```

`StatusOut` in `Protected\Logic`

```iecst
METHOD PROTECTED StatusOut //Set output status information
sts.stopped 	:= sts.state = E_TemplateDeviceState.Stopped;
sts.starting 	:= sts.state = E_TemplateDeviceState.Starting;
sts.running 	:= sts.state = E_TemplateDeviceState.Running;
sts.stopping 	:= sts.state = E_TemplateDeviceState.Stopping;

sts.readyToStart	:= runIntlk.sts.ok AND runPerm.sts.ok;
sts.echoRunFdbk 	:= runFdbkProcessed;
sts.echoRunOut 		:= outRun;
```

`Stop` in `Public\Commands`

```iecst
METHOD PUBLIC Stop
pcmd := E_TemplateDeviceCommand.Stop;
```

## Station: `FB_TemplateStation`

A module with one device: stops it while homing, runs it while started, stops it while stopping.

### Types

`E_TemplateStationRunStep`

```iecst
{attribute 'qualified_only'}
{attribute 'strict'}
{attribute 'to_string'}
TYPE E_TemplateStationRunStep :
(
	Idle		:= 0, //not running
	Run			:= 10, //device running
	Done		:= 20 //sequence finished
);
END_TYPE
```

`ST_TemplateStationStatus`

```iecst
TYPE ST_TemplateStationStatus :
STRUCT
	runStep				: E_TemplateStationRunStep := E_TemplateStationRunStep.Idle; //running sequence step
END_STRUCT
END_TYPE
```

### Function block

```iecst
FUNCTION_BLOCK FB_TemplateStation EXTENDS FB_Module
(*
	Template station: one device that runs while the station is started.
	Copy, rename "TemplateStation", add devices and run steps.
*)
VAR_INPUT
	(* Devices
	----------------------------------------------------------------------------------------------------*)
	{attribute 'OPC.UA.DA' := '1'}
	{attribute 'OPC.UA.DA.StructuredType' := '1'}
	device				: FB_TemplateDevice := (cfg := (deviceId := 'Device 1', noFdbk := TRUE));
END_VAR
VAR_OUTPUT
	{attribute 'OPC.UA.DA' := '1'}
	{attribute 'OPC.UA.DA.Access' := '1'}
	{attribute 'OPC.UA.DA.StructuredType' := '1'}
	stsStation			: ST_TemplateStationStatus; //station specific status (module status is in sts)
END_VAR
VAR
END_VAR

SUPER^();

Devices();
Permissives();
```

`Devices` in `Protected\Logic`

```iecst
METHOD PROTECTED Devices //call child devices
device(parentCtrl := childCtrl);

inpChildFaulted := device.fault.active;
```

`Permissives` in `Protected\Logic`

```iecst
METHOD PROTECTED Permissives //set module permissives and interlocks
//Homing is complete when the device is stopped
PermStartComplete.cfg.condText[0] := 'Device stopped';
PermStartComplete.perm.0 := device.sts.stopped;

//Stopping is complete when the device is stopped or faulted
PermStopComplete.cfg.condText[0] := 'Device stopped or faulted';
PermStopComplete.perm.0 := device.sts.stopped OR device.fault.active;

//A faulted device stops the station
IntlkAuto.cfg.condText[0] := 'Device not faulted';
IntlkAuto.perm.0 := NOT device.fault.active;
```

`Reset` in `Public\Control`

```iecst
METHOD Reset : BOOL
device.Reset();
Reset := TRUE;
```

`Started` in `Protected\States`

```iecst
METHOD PROTECTED Started : BOOL
CASE stsStation.runStep OF
	
	E_TemplateStationRunStep.Idle:
		stsStation.runStep := E_TemplateStationRunStep.Run;
		
	E_TemplateStationRunStep.Run:
		IF NOT device.sts.running AND NOT device.sts.starting THEN
			device.Start();
		END_IF
		
	E_TemplateStationRunStep.Done:
		;
		
END_CASE
```

`Starting` in `Protected\States`

```iecst
METHOD PROTECTED Starting : BOOL
//Homing: make sure the device is stopped
IF device.sts.running OR device.sts.starting THEN
	device.Stop();
END_IF
stsStation.runStep := E_TemplateStationRunStep.Idle;
```

`Stopping` in `Protected\States`

```iecst
METHOD PROTECTED Stopping : BOOL
IF device.sts.running OR device.sts.starting THEN
	device.Stop();
END_IF
stsStation.runStep := E_TemplateStationRunStep.Idle;
```

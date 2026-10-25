"""
PLC-Template OPC UA dashboard.

Reads the example machine's status from the TwinCAT OPC UA server (TF6100) and serves
a small web page at http://localhost:8080. Only the variables in WRITABLE can be written.

Run:  python app.py
      python app.py --browse   writes what the server publishes to opcua-tree.txt and exits
Login: set OPCUA_USER / OPCUA_PASSWORD, or you'll be asked at startup.
"""
import asyncio
import dataclasses
import datetime
import enum
import getpass
import json
import logging
import os
import socket
import sys
from pathlib import Path

from aiohttp import web
from asyncua import Client, ua
from asyncua.crypto.cert_gen import setup_self_signed_certificate
from asyncua.ua import uaerrors
from cryptography.x509.oid import ExtendedKeyUsageOID

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text())
log = logging.getLogger("dashboard")

# Server refused the login: retrying with the same user name and password can't succeed.
AUTH_ERRORS = (uaerrors.BadUserAccessDenied, uaerrors.BadIdentityTokenInvalid,
               uaerrors.BadIdentityTokenRejected, uaerrors.BadUserSignatureInvalid)
# Server doesn't trust the dashboard's certificate yet: retrying is right, once it's trusted it connects.
CERT_ERRORS = (uaerrors.BadSecurityChecksFailed, uaerrors.BadCertificateUntrusted)


class LoginRejected(Exception):
    pass

M = "MAIN.machine"
ST = f"{M}.exampleStation"
TR = f"{ST}.transaction"
SIM = "MAIN.softwareSim"

# Every PLC variable the page shows (paths below the PLC root node, e.g. PLC1).
TAGS = [
    # Machine
    f"{M}.sts.State", f"{M}.sts.Mode", f"{M}.sts.Faulted", f"{M}.sts.ReadyToStart",
    # Station
    f"{ST}.sts.State", f"{ST}.sts.Faulted",
    f"{ST}.stsStation.runStep", f"{ST}.stsStation.allOpen", f"{ST}.stsStation.allClosed",
    f"{ST}.stsStation.cycleCount", f"{ST}.stsStation.lastCycleTime",
    f"{ST}.stsStation.jobsRejected", f"{ST}.stsStation.lastRejectText", f"{ST}.stsStation.commError",
    f"{ST}.stsStation.job.cycleId", f"{ST}.stsStation.job.closeDwell",
    # Transaction (trigger/tell)
    f"{TR}.sts.state", f"{TR}.sts.bError", f"{TR}.sts.errorID",
    f"{TR}.handshake.attention", f"{TR}.handshake.trigger", f"{TR}.handshake.trigger_ack",
    f"{TR}.handshake.tell", f"{TR}.handshake.tell_ack",
    f"{TR}.request.cycleId", f"{TR}.request.closeDwell",
    f"{TR}.response.cycleId", f"{TR}.response.cycleTime", f"{TR}.response.ok",
    # Software simulator
    f"{SIM}.sts.step", f"{SIM}.sts.requestsSent", f"{SIM}.sts.responsesReceived", f"{SIM}.sts.aborts",
    f"{SIM}.sts.lastResponse.cycleId", f"{SIM}.sts.lastResponse.cycleTime", f"{SIM}.sts.lastResponse.ok",
    f"{SIM}.cfg.enable", f"{SIM}.cfg.freeze", f"{SIM}.cfg.sendInvalidRequest", f"{SIM}.cfg.closeDwell",
]
for a in ("actuatorA", "actuatorB"):
    TAGS += [f"{ST}.{a}.sts.state", f"{ST}.{a}.sts.mode", f"{ST}.{a}.fault.active", f"{ST}.{a}.fault.text"]

# The only variables the page may write.
WRITABLE = {
    f"{M}.ocmd",
    f"{SIM}.cfg.enable", f"{SIM}.cfg.freeze", f"{SIM}.cfg.sendInvalidRequest", f"{SIM}.cfg.closeDwell",
}


class Plc:
    """OPC UA connection, tag resolution and polling."""

    def __init__(self, user, password, ask_login=None):
        self.user, self.password = user, password
        self.ask_login = ask_login  # called to get a new login after a rejected one (None = give up)
        self.client = None
        self.connected = False
        self.error = "Connecting..."
        self.values = {}
        self.missing = []
        self.leaf = {}        # path -> Node
        self.nested = {}      # path -> (ancestor Node, [attribute names]) for members only exposed inside a structure
        self._children = {}

    # ------------------------------------------------------------------ connection
    async def run(self):
        while True:
            try:
                await self._connect()
                await self._resolve()
                self.connected, self.error = True, ""
                log.info("Connected, %d tags (%d missing)", len(TAGS) - len(self.missing), len(self.missing))
                while True:
                    await self._poll()
                    await asyncio.sleep(CONFIG["pollIntervalMs"] / 1000)
            except asyncio.CancelledError:
                raise
            except AUTH_ERRORS as e:
                await self._disconnect()
                self.connected = False
                self.error = f"Login rejected for user '{self.user or 'anonymous'}' ({type(e).__name__})"
                log.error("%s", self.error)
                if self.ask_login is None:
                    raise LoginRejected(self.error) from e
                self.user, self.password = await asyncio.to_thread(self.ask_login)
                continue
            except CERT_ERRORS as e:
                self.connected = False
                self.error = (f"{type(e).__name__}: the server does not trust the dashboard certificate yet. "
                              f"Trust 'PLC-Template Dashboard' in the OPC UA Configurator (see README).")
                log.warning("%s Retrying in 5 s", self.error)
                await self._disconnect()
                await asyncio.sleep(5)
            except Exception as e:  # keep the dashboard up and retry
                self.connected, self.error = False, f"{type(e).__name__}: {e}"
                log.warning("OPC UA: %s, retrying in 3 s", self.error)
                await self._disconnect()
                await asyncio.sleep(3)

    async def _connect(self):
        self.client = Client(CONFIG["endpoint"], timeout=5)
        self.client.application_uri = f"urn:{socket.gethostname()}:PLC-Template:Dashboard"
        self.client.name = "PLC-Template Dashboard"
        if self.user:
            self.client.set_user(self.user)
            self.client.set_password(self.password)
        if CONFIG.get("security", "None") != "None":
            pki = HERE / "pki"
            pki.mkdir(exist_ok=True)
            key, cert = pki / "dashboard-key.pem", pki / "dashboard-cert.der"
            await setup_self_signed_certificate(
                key, cert, self.client.application_uri, socket.gethostname(),
                [ExtendedKeyUsageOID.CLIENT_AUTH], {"commonName": "PLC-Template Dashboard"})
            await self.client.set_security_string(f"{CONFIG['security']},{cert},{key}")
        await self.client.connect()
        try:
            await self.client.load_data_type_definitions()
        except Exception as e:
            log.info("Could not load structure definitions (%s); structures are read member by member", e)

    async def _disconnect(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.client, self._children = None, {}

    # ------------------------------------------------------------------ tag lookup by browse name
    async def _child(self, node, name):
        key = node.nodeid.to_string()
        if key not in self._children:
            self._children[key] = {
                (await c.read_browse_name()).Name.lower(): c for c in await node.get_children()}
        return self._children[key].get(name.lower())

    async def _find(self, path):
        """Return (node, remaining attributes). remaining is empty for a directly exposed variable."""
        node = await self._child(self.client.nodes.objects, CONFIG["plcRoot"])
        if node is None:
            raise RuntimeError(f"No '{CONFIG['plcRoot']}' node under Objects. Is the PLC running and "
                               f"is 'plcRoot' in config.json correct?")
        parts = path.split(".")
        for i, part in enumerate(parts):
            nxt = await self._child(node, part)
            if nxt is None:
                if i > 0 and await node.read_node_class() == ua.NodeClass.Variable:
                    return node, parts[i:]
                return None, parts[i:]
            node = nxt
        return node, []

    async def _resolve(self):
        self.leaf, self.nested, self.missing = {}, {}, []
        for path in sorted(set(TAGS) | WRITABLE):
            node, rest = await self._find(path)
            if node is None:
                self.missing.append(path)
            elif rest:
                self.nested[path] = (node, rest)
            else:
                self.leaf[path] = node
        if self.missing:
            log.warning("Not found on the server (missing OPC.UA.DA attribute?):\n  %s", "\n  ".join(self.missing))

    # ------------------------------------------------------------------ polling
    async def _poll(self):
        nodes = {p: n for p, n in self.leaf.items()}
        for p, (n, _) in self.nested.items():
            nodes[f"__struct__{n.nodeid.to_string()}"] = n
        keys = list(nodes)
        vals = dict(zip(keys, await self.client.read_values([nodes[k] for k in keys])))
        out = {p: to_json(vals[p]) for p in self.leaf}
        for p, (n, rest) in self.nested.items():
            v = vals[f"__struct__{n.nodeid.to_string()}"]
            for attr in rest:
                v = get_ci(v, attr)
            out[p] = to_json(v)
        self.values = out

    async def write(self, path, value):
        if path not in WRITABLE:
            raise PermissionError(f"{path} is not writable from the dashboard")
        if not self.connected:
            raise ConnectionError("Not connected to the PLC")
        node = self.leaf.get(path)
        if node is None:
            raise LookupError(f"{path} is not exposed as its own OPC UA variable")
        vtype = await node.read_data_type_as_variant_type()
        if vtype == ua.VariantType.Boolean:
            value = bool(value)
        elif vtype in (ua.VariantType.Float, ua.VariantType.Double):
            value = float(value)
        elif vtype == ua.VariantType.String:
            value = str(value)
        else:
            value = int(value)
        await node.write_value(ua.DataValue(ua.Variant(value, vtype)))


def ask_login():
    print("\nOPC UA login (the account set up when the TF6100 server was initialized).")
    print("Windows accounts: try just the user name, then COMPUTERNAME\\user. Ctrl+C to quit.")
    user = input("User (blank for anonymous): ").strip() or None
    password = getpass.getpass("Password: ") if user else None
    return user, password


def get_ci(obj, name):
    """Case-insensitive attribute lookup on a decoded structure."""
    if obj is None:
        return None
    for f in (dataclasses.fields(obj) if dataclasses.is_dataclass(obj) else []):
        if f.name.lower() == name.lower():
            return getattr(obj, f.name)
    return getattr(obj, name, None)


def to_json(v):
    if isinstance(v, enum.Enum):
        return v.value
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, datetime.timedelta):
        return v.total_seconds() * 1000
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if dataclasses.is_dataclass(v):
        return {f.name: to_json(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, (list, tuple)):
        return [to_json(x) for x in v]
    return v


# ---------------------------------------------------------------------- web server
async def browse(plc, out_file, max_depth=12):
    """Write the server's tree below the PLC node, to compare with TAGS."""
    while True:
        try:
            await plc._connect()
            break
        except AUTH_ERRORS as e:
            print(f"Login rejected ({type(e).__name__})")
            await plc._disconnect()
            if plc.ask_login is None:
                raise LoginRejected("Login rejected") from e
            plc.user, plc.password = plc.ask_login()
    lines = [f"# {CONFIG['endpoint']}  root: Objects/{CONFIG['plcRoot']}"]
    count = 0

    async def walk(node, path, depth):
        nonlocal count
        for c in await node.get_children():
            name = (await c.read_browse_name()).Name
            cls = await c.read_node_class()
            info = cls.name
            if cls == ua.NodeClass.Variable:
                try:
                    info += f" {(await c.read_data_type_as_variant_type()).name}"
                except Exception:
                    info += " ?"
            p = f"{path}.{name}" if path else name
            lines.append(f"{'  ' * depth}{name}  [{info}]  {p}  ({c.nodeid.to_string()})")
            count += 1
            if depth < max_depth and cls in (ua.NodeClass.Object, ua.NodeClass.Variable):
                await walk(c, p, depth + 1)

    try:
        root = await plc._child(plc.client.nodes.objects, CONFIG["plcRoot"])
        if root is None:
            names = [(await c.read_browse_name()).Name for c in await plc.client.nodes.objects.get_children()]
            lines.append(f"!! No '{CONFIG['plcRoot']}' under Objects. Objects contains: {names}")
        else:
            await walk(root, "", 0)
        await plc._resolve()
        lines.append("")
        lines.append(f"# Dashboard tags not found ({len(plc.missing)}):")
        lines += [f"#   {m}" for m in plc.missing]
    finally:
        out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        await plc._disconnect()
    print(f"Wrote {count} nodes to {out_file}, {len(plc.missing)} dashboard tags not found")


def make_app(plc):
    app = web.Application()

    async def index(_):
        return web.FileResponse(HERE / "index.html")

    async def state(_):
        return web.json_response({"connected": plc.connected, "error": plc.error,
                                  "endpoint": CONFIG["endpoint"], "values": plc.values,
                                  "missing": plc.missing, "writable": sorted(WRITABLE)})

    async def write(request):
        body = await request.json()
        try:
            await plc.write(body["path"], body["value"])
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    app.router.add_get("/", index)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/write", write)
    return app


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("asyncua").setLevel(logging.ERROR)
    interactive = sys.stdin.isatty()
    user = os.environ.get("OPCUA_USER")
    password = os.environ.get("OPCUA_PASSWORD")
    if user is None and interactive:
        user, password = ask_login()
    plc = Plc(user, password, ask_login if interactive else None)
    if "--browse" in sys.argv:
        await browse(plc, HERE / "opcua-tree.txt")
        return

    runner = web.AppRunner(make_app(plc))
    await runner.setup()
    # localhost only: the page can start and stop the machine
    await web.TCPSite(runner, "127.0.0.1", CONFIG["httpPort"]).start()
    log.info("Dashboard at http://localhost:%d  (OPC UA %s)", CONFIG["httpPort"], CONFIG["endpoint"])
    await plc.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except LoginRejected as e:
        print(f"\n{e}. Check OPCUA_USER / OPCUA_PASSWORD and run again.")
        sys.exit(1)

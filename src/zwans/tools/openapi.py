"""The OpenAPI tool: an API understood from its OpenAPI 3 or Swagger 2 spec.

A spec is the most exact description of an API there is, and among the hardest files to
read: thousands of lines of JSON where one endpoint's request body is three `$ref`s away
from the endpoint. This reads the spec from a file, or from a server on this machine or the
local network (FastAPI serves one at /openapi.json), and answers in two ways. Without a
filter it's a map: title, servers, how to authenticate, and every endpoint on one line,
grouped by tag. Narrowed to a few endpoints, each comes in full: its parameters, request
body and responses, with the `$ref`s followed and the schemas written as compact
TypeScript-like shapes (`{ id: integer, name?: string }`).

The policy judges a call that fetches a URL as a network request to its host; one that reads
a file is judged like reading it.
"""

import ipaddress
import json
import re
from collections.abc import Iterator
from typing import Any

import httpx
from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.http import _is_public
from zwans.tools.web_local import Resolver, host_of, resolve

TIMEOUT = 20.0
MAX_ENDPOINTS = 150  # one-line endpoints in the map
MAX_DETAILED = 5  # operations shown in full
MAX_DEPTH = 4  # nesting of a schema shape before it's cut to its name
MAX_SHAPE_CHARS = 1_500
MAX_ENUM = 8
MAX_OUTPUT_CHARS = 30_000
MAX_YAML_ARG = 500_000  # bytes of YAML passed to Python on its command line
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
YAML_TO_JSON = (
    "import json, sys, yaml\nprint(json.dumps(yaml.safe_load(sys.argv[1]), default=str))\n"
)


class OpenAPIInput(BaseModel):
    source: str = Field(
        description="The spec: a file in the workspace (JSON or YAML), or a URL on this "
        'machine or the local network, as "http://localhost:8000/openapi.json".'
    )
    endpoint: str = Field(
        default="",
        description='Show endpoints in full: a piece of their path ("/users"), an operationId, '
        'or a method and path ("GET /users/{id}"). Leave it empty for the map of the API.',
    )
    tag: str = Field(default="", description="Only endpoints with this tag.")


class OpenAPITool:
    name = "OpenAPI"
    description = (
        "Understand an API from its OpenAPI 3 or Swagger 2 spec, from a file or a URL on this "
        "machine or the local network (as FastAPI's /openapi.json). Without a filter: the "
        "title, servers, auth and every endpoint on one line, grouped by tag. With endpoint "
        "or tag narrowed to a few operations: their parameters, request body and responses, "
        "$refs followed, schemas shown as TypeScript-like shapes."
    )
    input_model = OpenAPIInput
    read_only = True

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, resolver: Resolver = resolve
    ) -> None:
        self.transport = transport
        self.resolver = resolver

    def host(self, args: dict[str, Any]) -> str | None:
        """The host a URL source reaches; None for a file, judged like reading it."""
        return host_of(args.get("source")) or None

    def read_paths(self, args: dict[str, Any]) -> list[str]:
        """A file source, for the policy, so a Read rule covers it."""
        source = args.get("source")
        return [source] if isinstance(source, str) and not host_of(source) else []

    async def run(self, args: OpenAPIInput, ctx: ToolContext) -> ToolOutput:
        source = args.source.strip()
        if not source:
            raise ToolError("source is empty: give a spec file or a URL.")
        spec = await self._load(source, ctx)
        api = Spec(spec, source)
        operations = list(api.operations())
        if args.tag.strip():
            tag = args.tag.strip().lower()
            operations = [op for op in operations if tag in (t.lower() for t in op.tags)]
            if not operations:
                tags = ", ".join(api.tag_names()) or "none"
                raise ToolError(f"No endpoint has the tag {args.tag!r}. The tags are: {tags}.")
        if args.endpoint.strip():
            operations = _matching(operations, args.endpoint.strip())
            if not operations:
                raise ToolError(
                    f"No endpoint matches {args.endpoint!r}. Leave endpoint empty to see them all."
                )
        narrowed = bool(args.tag.strip() or args.endpoint.strip())
        if narrowed and len(operations) <= MAX_DETAILED:
            text = "\n\n".join(api.detail(op) for op in operations)
        else:
            text = api.overview(operations, narrowed)
        if len(text) > MAX_OUTPUT_CHARS:
            cut = len(text) - MAX_OUTPUT_CHARS
            text = text[:MAX_OUTPUT_CHARS] + f"\n[... {cut:,} more characters: narrow it down]"
        return ToolOutput(content=text)

    async def _load(self, source: str, ctx: ToolContext) -> dict[str, Any]:
        if re.match(r"(?i)https?://", source):
            text = await self._fetch(source)
        elif "://" in source:
            raise ToolError(f"{source!r} isn't a file or an http(s) URL.")
        else:
            try:
                data = await ctx.executor.read_bytes(source)
            except FileNotFoundError as exc:
                raise ToolError(f"There is no file {source}.") from exc
            except IsADirectoryError as exc:
                raise ToolError(f"{source} is a folder, not a spec file.") from exc
            text = data.decode("utf-8", "replace")
        try:
            spec = json.loads(text)
        except ValueError:
            spec = await _from_yaml(text, source, ctx)
        if not isinstance(spec, dict) or not ("openapi" in spec or "swagger" in spec):
            raise ToolError(
                f"{source} doesn't look like an OpenAPI or Swagger spec: it has no openapi or "
                "swagger field at the top."
            )
        return spec

    async def _fetch(self, url: str) -> str:
        host = host_of(url)
        if not host:
            raise ToolError(f"{url!r} isn't a URL OpenAPI can fetch.")
        await self._check_local(host)
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=TIMEOUT) as client:
                reply = await client.get(url, headers={"Accept": "application/json, */*"})
        except httpx.ConnectError as exc:
            raise ToolError(f"Nothing answered at {url}: is the server running?") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"Fetching {url} failed: {exc or type(exc).__name__}") from exc
        if reply.status_code >= 400:
            raise ToolError(f"{url} answered HTTP {reply.status_code} {reply.reason_phrase}.")
        return reply.text

    async def _check_local(self, host: str) -> None:
        try:
            addresses = [str(ipaddress.ip_address(host.strip("[]")))]
        except ValueError:
            try:
                addresses = await self.resolver(host)
            except OSError as exc:
                raise ToolError(f"Couldn't find {host}: {exc}") from exc
        if not addresses or any(_is_public(address) for address in addresses):
            raise ToolError(
                f"{host} is on the public internet, and OpenAPI only fetches from this machine "
                "and the local network. Save the spec to a file and pass its path instead."
            )


async def _from_yaml(text: str, source: str, ctx: ToolContext) -> Any:
    """YAML, converted by the project's Python if it has PyYAML (Zwans itself doesn't)."""
    hint = "Use the JSON version of the spec if there is one (FastAPI serves /openapi.json)."
    if len(text.encode()) > MAX_YAML_ARG:
        raise ToolError(f"{source} is YAML too large to convert here. {hint}")
    result = await ctx.executor.run(["python", "-I", "-c", YAML_TO_JSON, text], timeout=60)
    if result.exit_code != 0:
        if "No module named" in result.output and "yaml" in result.output:
            raise ToolError(
                f"{source} is YAML, and reading YAML needs PyYAML, which the project's Python "
                f"doesn't have. {hint}"
            )
        last = result.output.strip().splitlines()[-1:] or ["Python couldn't run"]
        raise ToolError(f"{source} couldn't be read as JSON or YAML: {last[0]}")
    try:
        return json.loads(result.output)
    except ValueError as exc:
        raise ToolError(f"{source} couldn't be converted from YAML. {hint}") from exc


class Operation:
    def __init__(self, method: str, path: str, body: dict[str, Any], shared: list[Any]) -> None:
        self.method = method.upper()
        self.path = path
        self.body = body
        self.shared = shared  # the path's own parameters
        tags = body.get("tags")
        self.tags: list[str] = [str(t) for t in tags] if isinstance(tags, list) and tags else []
        self.summary = _summary(body)
        self.id = str(body.get("operationId") or "")
        self.deprecated = bool(body.get("deprecated"))


def _summary(body: dict[str, Any]) -> str:
    for key in ("summary", "description", "operationId"):
        text = body.get(key)
        if isinstance(text, str) and text.strip():
            return " ".join(text.strip().splitlines()[0].split())[:100]
    return ""


def _matching(operations: list[Operation], wanted: str) -> list[Operation]:
    match = re.fullmatch(r"(?i)(get|put|post|delete|options|head|patch|trace)\s+(\S+)", wanted)
    if match:
        method, path = match.group(1).upper(), match.group(2)
        same = [op for op in operations if op.method == method]
        exact = [op for op in same if op.path == path]
        return exact or [op for op in same if path.lower() in op.path.lower()]
    by_id = [op for op in operations if op.id and op.id == wanted]
    if by_id:
        return by_id
    exact = [op for op in operations if op.path == wanted]
    return exact or [op for op in operations if wanted.lower() in op.path.lower()]


class Spec:
    def __init__(self, spec: dict[str, Any], source: str) -> None:
        self.spec = spec
        self.source = source
        self.swagger = "swagger" in spec and "openapi" not in spec

    # -- the map

    def operations(self) -> Iterator[Operation]:
        paths = self.spec.get("paths")
        if not isinstance(paths, dict):
            return
        for path, item in paths.items():
            item = self.resolve(item)
            if not isinstance(item, dict):
                continue
            shared = item.get("parameters")
            for method in METHODS:
                body = item.get(method)
                if isinstance(body, dict):
                    yield Operation(
                        method, str(path), body, shared if isinstance(shared, list) else []
                    )

    def tag_names(self) -> list[str]:
        names: list[str] = []
        for entry in self.spec.get("tags") or []:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                names.append(entry["name"])
        for op in self.operations():
            names += [tag for tag in op.tags if tag not in names]
        return names

    def overview(self, operations: list[Operation], narrowed: bool) -> str:
        found = self.spec.get("info")
        info: dict[str, Any] = found if isinstance(found, dict) else {}
        if self.swagger:
            kind = f"Swagger {self.spec.get('swagger')}"
        else:
            kind = f"OpenAPI {self.spec.get('openapi')}"
        title = str(info.get("title") or "(untitled)")
        version = f" {info['version']}" if info.get("version") else ""
        lines = [f"{title}{version} ({kind}, from {self.source})"]
        description = info.get("description")
        if isinstance(description, str) and description.strip():
            lines.append(" ".join(description.strip().splitlines()[0].split())[:300])
        servers = self.servers()
        if servers:
            lines.append("Servers: " + ", ".join(servers))
        lines += self.auth_lines()
        if narrowed:
            lines.append(
                f"\n{len(operations)} endpoints match; narrow it to {MAX_DETAILED} or fewer to "
                "see them in full."
            )
        else:
            lines.append(f"\n{len(operations)} endpoints:")
        order = self.tag_names()
        groups: dict[str, list[Operation]] = {}
        for op in operations:
            groups.setdefault(op.tags[0] if op.tags else "", []).append(op)
        keys = [t for t in order if t in groups] + ([""] if "" in groups else [])
        shown = 0
        width = max((len(op.path) for op in operations[:MAX_ENDPOINTS]), default=0)
        width = min(width, 60)
        for key in keys:
            if shown >= MAX_ENDPOINTS:
                break
            lines.append(f"\n[{key or 'no tag'}]")
            for op in groups[key]:
                if shown >= MAX_ENDPOINTS:
                    break
                note = " (deprecated)" if op.deprecated else ""
                lines.append(f"  {op.method:<7} {op.path:<{width}}  {op.summary}{note}".rstrip())
                shown += 1
        if len(operations) > shown:
            lines.append(
                f"\n({len(operations) - shown} more endpoints not shown. Narrow it with tag, or "
                "with endpoint as a piece of the path.)"
            )
        if not narrowed:
            lines.append(
                '\n(For an endpoint in full, pass endpoint, as "GET /users/{id}" or "/users".)'
            )
        return "\n".join(lines)

    def servers(self) -> list[str]:
        if self.swagger:
            host = self.spec.get("host")
            if not host:
                return []
            schemes = self.spec.get("schemes") or ["https"]
            base = self.spec.get("basePath") or ""
            return [f"{scheme}://{host}{base}" for scheme in schemes if isinstance(scheme, str)]
        found = []
        for server in self.spec.get("servers") or []:
            if isinstance(server, dict) and server.get("url"):
                found.append(str(server["url"]))
        return found

    def auth_lines(self) -> list[str]:
        if self.swagger:
            schemes = self.spec.get("securityDefinitions")
        else:
            components = self.spec.get("components")
            schemes = components.get("securitySchemes") if isinstance(components, dict) else None
        if not isinstance(schemes, dict) or not schemes:
            return []
        lines = ["Auth:"]
        for name, scheme in schemes.items():
            scheme = self.resolve(scheme)
            if isinstance(scheme, dict):
                lines.append(f"  {name}: {_scheme_text(scheme)}")
        required = _requirement_names(self.spec.get("security"))
        if required:
            lines.append(f"  (required on every endpoint unless it says otherwise: {required})")
        return lines

    # -- one operation in full

    def detail(self, op: Operation) -> str:
        head = f"{op.method} {op.path}"
        if op.summary:
            head += f" - {op.summary}"
        lines = [head]
        facts = []
        if op.id:
            facts.append(f"operationId: {op.id}")
        if op.tags:
            facts.append(f"tags: {', '.join(op.tags)}")
        if op.deprecated:
            facts.append("deprecated")
        if facts:
            lines.append("  ".join(facts))
        description = op.body.get("description")
        if (
            isinstance(description, str)
            and description.strip()
            and description.strip() != (op.body.get("summary") or "").strip()
        ):
            text = " ".join(description.split())
            lines.append(text[:400] + ("..." if len(text) > 400 else ""))
        security = op.body.get("security", self.spec.get("security"))
        auth = _requirement_names(security)
        if auth:
            lines.append(f"Auth: {auth}")
        elif isinstance(security, list):
            lines.append("Auth: none")

        parameters, body_params = self.parameters(op)
        if parameters:
            lines.append("Parameters:")
            rows = []
            for param in parameters:
                kind = self.param_type(param)
                required = "required" if param.get("required") else ""
                about = " ".join(str(param.get("description") or "").split())[:120]
                rows.append(
                    (str(param.get("in", "")), str(param.get("name", "")), kind, required, about)
                )
            widths = [max(len(row[i]) for row in rows) for i in range(4)]
            for row in rows:
                cells = [row[i].ljust(widths[i]) for i in range(4)] + [row[4]]
                lines.append(("  " + "  ".join(cells)).rstrip())
        lines += self.request_body(op, body_params)
        lines += self.responses(op)
        return "\n".join(lines)

    def parameters(self, op: Operation) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for raw in [*op.shared, *(op.body.get("parameters") or [])]:
            param = self.resolve(raw)
            if isinstance(param, dict):
                merged[(str(param.get("in")), str(param.get("name")))] = param
        plain = [p for p in merged.values() if p.get("in") not in ("body", "formData")]
        body = [p for p in merged.values() if p.get("in") in ("body", "formData")]
        return plain, body

    def param_type(self, param: dict[str, Any]) -> str:
        if isinstance(param.get("schema"), dict):
            return self.shape(param["schema"])
        if "content" in param and isinstance(param["content"], dict):
            for media in param["content"].values():
                if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                    return self.shape(media["schema"])
        return self.shape(param)  # Swagger 2: the type is on the parameter itself

    def request_body(self, op: Operation, body_params: list[dict[str, Any]]) -> list[str]:
        if self.swagger:
            lines = []
            for param in body_params:
                if param.get("in") == "body":
                    required = ", required" if param.get("required") else ""
                    schema = param.get("schema") if isinstance(param.get("schema"), dict) else {}
                    lines.append(f"Request body{required}: {self.shape(schema)}")
            form = [p for p in body_params if p.get("in") == "formData"]
            if form:
                fields = ", ".join(
                    f"{p.get('name')}{'' if p.get('required') else '?'}: {self.shape(p)}"
                    for p in form
                )
                lines.append(f"Request body (form): {{ {fields} }}")
            return lines
        body = self.resolve(op.body.get("requestBody"))
        if not isinstance(body, dict):
            return []
        required = ", required" if body.get("required") else ""
        content = body.get("content")
        if not isinstance(content, dict) or not content:
            return [f"Request body{required}"]
        lines = []
        for media, entry in content.items():
            schema = entry.get("schema") if isinstance(entry, dict) else None
            shape = self.shape(schema) if isinstance(schema, dict) else "(no schema)"
            lines.append(f"Request body ({media}{required}): {shape}")
        return lines

    def responses(self, op: Operation) -> list[str]:
        responses = op.body.get("responses")
        if not isinstance(responses, dict) or not responses:
            return []
        lines = ["Responses:"]
        for status, raw in responses.items():
            response = self.resolve(raw)
            if not isinstance(response, dict):
                continue
            about = " ".join(str(response.get("description") or "").split())[:100]
            if self.swagger:
                schema = response.get("schema")
                shapes = [("", self.shape(schema))] if isinstance(schema, dict) else []
            else:
                content = response.get("content")
                shapes = []
                if isinstance(content, dict):
                    for media, entry in content.items():
                        schema = entry.get("schema") if isinstance(entry, dict) else None
                        if isinstance(schema, dict):
                            shapes.append((media, self.shape(schema)))
            if not shapes:
                lines.append(f"  {status}: {about}".rstrip(": ").rstrip())
            for media, shape in shapes[:3]:
                where = f" ({media})" if media else ""
                lines.append(f"  {status}{where}: {shape}" + (f"  - {about}" if about else ""))
        return lines

    # -- references and shapes

    def resolve(self, value: Any, depth: int = 0) -> Any:
        """A $ref followed (to a name in this spec), or the value itself."""
        while isinstance(value, dict) and isinstance(value.get("$ref"), str) and depth < 20:
            target = self.pointer(value["$ref"])
            if target is None:
                return value
            value = target
            depth += 1
        return value

    def pointer(self, ref: str) -> Any:
        if not ref.startswith("#/"):
            return None  # in another file
        node: Any = self.spec
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                return None
        return node

    def shape(self, schema: Any) -> str:
        text = self._shape(schema, 0, frozenset())
        ref = schema.get("$ref") if isinstance(schema, dict) else None
        if isinstance(ref, str) and text.startswith("{"):
            text = f"{ref.rsplit('/', 1)[-1]} {text}"  # the schema's name, then its shape
        if len(text) > MAX_SHAPE_CHARS:
            text = text[:MAX_SHAPE_CHARS] + " ..."
        return text

    def _shape(self, schema: Any, depth: int, seen: frozenset[str]) -> str:
        if not isinstance(schema, dict):
            return "any"
        ref = schema.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            target = self.pointer(ref)
            if target is None:
                return name or ref
            if ref in seen or depth >= MAX_DEPTH:
                return name
            inner = self._shape(target, depth, seen | {ref})
            return inner
        nullable = bool(schema.get("nullable")) or schema.get("x-nullable") is True
        for key, joiner in (("oneOf", " | "), ("anyOf", " | "), ("allOf", " & ")):
            options = schema.get(key)
            if isinstance(options, list) and options:
                parts = [self._shape(option, depth, seen) for option in options]
                parts = [_wrapped(part) for part in dict.fromkeys(parts)]
                if key == "allOf" and len(parts) == 1:
                    return parts[0] + (" | null" if nullable else "")
                text = joiner.join(parts)
                return text + (" | null" if nullable else "")
        if "const" in schema:
            return json.dumps(schema["const"])
        enum = schema.get("enum")
        if isinstance(enum, list) and enum:
            values = [json.dumps(value) for value in enum[:MAX_ENUM]]
            if len(enum) > MAX_ENUM:
                values.append("...")
            return " | ".join(values) + (" | null" if nullable else "")
        kind = schema.get("type")
        if isinstance(kind, list):  # OpenAPI 3.1: ["string", "null"]
            parts = [self._shape({**schema, "type": each}, depth, seen) for each in kind]
            return " | ".join(parts)
        if kind == "array" or "items" in schema:
            item = self._shape(schema.get("items"), depth + 1, seen)
            text = f"{_wrapped(item)}[]"
        elif kind == "object" or "properties" in schema or "additionalProperties" in schema:
            text = self._object(schema, depth, seen)
        elif isinstance(kind, str):
            text = kind
            format_ = schema.get("format")
            if isinstance(format_, str) and kind in ("string", "integer", "number"):
                text = f"{kind}<{format_}>"
        else:
            text = "any"
        return text + (" | null" if nullable else "")

    def _object(self, schema: dict[str, Any], depth: int, seen: frozenset[str]) -> str:
        properties = schema.get("properties")
        extra = schema.get("additionalProperties")
        if depth >= MAX_DEPTH:
            return "{ ... }"
        fields = []
        if isinstance(properties, dict):
            required = schema.get("required")
            needed = set(required) if isinstance(required, list) else set()
            for name, value in properties.items():
                mark = "" if name in needed else "?"
                key = name if re.fullmatch(r"[A-Za-z_$][\w$]*", name) else json.dumps(name)
                fields.append(f"{key}{mark}: {self._shape(value, depth + 1, seen)}")
        if isinstance(extra, dict):
            fields.append(f"[key: string]: {self._shape(extra, depth + 1, seen)}")
        elif extra is True:
            fields.append("[key: string]: any")
        if not fields:
            return "object"
        return "{ " + ", ".join(fields) + " }"


def _wrapped(text: str) -> str:
    return f"({text})" if (" | " in text or " & " in text) and not text.startswith("{") else text


def _scheme_text(scheme: dict[str, Any]) -> str:
    kind = str(scheme.get("type", "?"))
    if kind == "http":
        text = f"HTTP {scheme.get('scheme', '')}".rstrip()
        if scheme.get("bearerFormat"):
            text += f" ({scheme['bearerFormat']})"
        return text
    if kind == "apiKey":
        return f"API key in the {scheme.get('in', '?')} {scheme.get('name', '?')!s}"
    if kind == "oauth2":
        flows = scheme.get("flows")
        if isinstance(flows, dict):
            names = ", ".join(flows)
            urls = [
                str(flow.get("tokenUrl") or flow.get("authorizationUrl") or "")
                for flow in flows.values()
                if isinstance(flow, dict)
            ]
            url = next((u for u in urls if u), "")
            return f"OAuth2 ({names})" + (f", {url}" if url else "")
        flow = scheme.get("flow")
        return f"OAuth2 ({flow})" if flow else "OAuth2"
    if kind == "openIdConnect":
        return f"OpenID Connect, {scheme.get('openIdConnectUrl', '')}".rstrip(", ")
    if kind == "basic":
        return "HTTP basic"
    return kind


def _requirement_names(security: Any) -> str:
    if not isinstance(security, list):
        return ""
    options = []
    for requirement in security:
        if isinstance(requirement, dict) and requirement:
            options.append(" + ".join(str(name) for name in requirement))
    return " or ".join(options)

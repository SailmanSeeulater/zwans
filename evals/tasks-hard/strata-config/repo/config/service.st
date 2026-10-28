# Ingest service configuration.

[defaults]
port = 8080
workers = 4

[server]
host = 0.0.0.0
port = ${defaults.port}
url = "http://${.host}:${.port}/"
workers ?= ${defaults.workers}

[server.tls]
enabled = false

[storage]
@include "storage.st"

[]
@include? "local.st"

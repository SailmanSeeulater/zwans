# The egress proxy: the only way out of the sandbox network, and only to allowed hosts.
# Build: docker build -t zwans-proxy:0.1 sandbox-image/proxy
FROM alpine:3.20
RUN apk add --no-cache tinyproxy
COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY allow.txt /etc/tinyproxy/allow.txt
EXPOSE 3128
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]

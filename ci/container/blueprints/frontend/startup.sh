#!/bin/sh
#
# Entrypoint for the frontend blueprint image.
#
# Renders the OpenTelemetry exporter configuration from the environment before
# starting nginx. ngx_otel_module takes its collector address from nginx config
# only and ignores the OTEL_* environment, so the address cannot simply be passed
# through as an env var -- it has to be written into a config file first.
#
# OTEL_EXPORTER_OTLP_ENDPOINT must be an OTLP/gRPC endpoint (port 4317 by
# convention); the module does not speak OTLP/HTTP. A scheme and path are
# tolerated and stripped. Leave the variable unset to run without tracing.

set -eu

OTEL_DIR=/etc/nginx/otel.d

if [ -d "$OTEL_DIR" ] && [ -n "${OTEL_EXPORTER_OTLP_ENDPOINT:-}" ]; then
    # http://collector.ns.svc.cluster.local:4317/ -> collector.ns.svc.cluster.local:4317
    endpoint=$(printf '%s' "$OTEL_EXPORTER_OTLP_ENDPOINT" \
        | sed -e 's|^[a-zA-Z][a-zA-Z0-9+.-]*://||' -e 's|/.*$||')

    cat > "$OTEL_DIR/exporter.conf" <<EOF
otel_exporter {
    endpoint ${endpoint};
}
otel_service_name ${OTEL_SERVICE_NAME:-nginx-service};
otel_trace ${OTEL_TRACE:-on};
otel_trace_context ${OTEL_TRACE_CONTEXT:-inject};
EOF
    #Generate otel_resouce_attributes entries from variable OTEL_RESOURCE_ATTRIBUTES
    if [ -n "${OTEL_RESOURCE_ATTRIBUTES:-}" ]; then
        IFS=',' read -r -a attributes <<< "$OTEL_RESOURCE_ATTRIBUTES"
        for attribute in "${attributes[@]}"; do
            key=$(printf '%s' "$attribute" | cut -d '=' -f 1)
            value=$(printf '%s' "$attribute" | cut -d '=' -f 2-)
            echo "otel_resource_attribute ${key} ${value};" >> "$OTEL_DIR/exporter.conf"
        done
    fi
fi

# Start the nginx server in foreground. exec so nginx is PID 1 and receives
# SIGTERM directly, otherwise the shell swallows it and shutdown is not graceful.
exec nginx

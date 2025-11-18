# Denodo Express 9.0 Docker Container
# Use official Denodo Express image from harbor.open.denodo.com
# Using SHA256 digest for exact version pinning
FROM harbor.open.denodo.com/denodo-express/denodo-platform@sha256:7e10101863621ed0656e525ec9463a487be867bc6a3a12b09293153929e3bb54

# Set environment variables
ENV DENODO_HOME=/opt/denodo
ENV JAVA_OPTS="-Xmx2g -Xms1g"

# License file will be mounted as volume (configurable via docker-compose)
# Default: denodo-express-lic-9-202511.lic → /opt/denodo/conf/denodo.lic

# Copy VQL scripts for initialization (will be mounted as volume in docker-compose)
# COPY denodo/init/*.vql /opt/denodo/init/

# Expose Denodo ports
# 9999: Virtual DataPort Server
# 9090: Web Container (REST API, Web Panel)
EXPOSE 9999 9090

# Health check - check if Denodo ports are listening
# Start period is 180s to allow full startup
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD bash -c 'timeout 5 bash -c "cat < /dev/null > /dev/tcp/localhost/9999 && cat < /dev/null > /dev/tcp/localhost/9090"' || exit 1

# Start Denodo Virtual DataPort Server
# The original entrypoint.sh script expects module arguments
CMD ["--vdpserver"]

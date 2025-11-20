# (c) 2021-2025
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#
ARG IMAGE_NAME=mcr.microsoft.com/dotnet/aspnet:9.0

FROM $IMAGE_NAME AS base

ARG DOTNET_OPTS="--configuration Release"
ARG OTEL_DOTNET_AUTO_HOME="/app/otel-dotnet-auto"
ARG APM_OPTS=""

ARG USER_ID=10001
ARG GROUP_ID=10001
ARG USER_NAME=webapp
ARG GROUP_NAME=webapp

## Stage 1: Create basic entries
USER root

RUN mkdir -p /app/webapp/

ENV OTEL_DOTNET_AUTO_HOME=${OTEL_DOTNET_AUTO_HOME}
# Copy the application configuarion as per the application
# Build process must ensure output jar is unique for each build
#<DOTNET-INJECTION-POINT>

# Stage 2: Customized configuation injection occurs at command line
FROM base AS customized
ARG OTEL_DOTNET_AUTO_HOME
ARG DOTNET_OPTS
ARG APM_OPTS

WORKDIR /app/webapp
#<DOCKER-INJECTION-POINT>

# Stage 3: Final image
FROM customized AS final
ARG OTEL_DOTNET_AUTO_HOME
ARG DOTNET_OPTS
ARG APM_OPTS

# Create the user and group use addgroup in cases OS supports elsewhere use groupadd
#RUN addgroup --gid $GROUP_ID --system $GROUP_NAME \
#    && adduser --uid $USER_ID --system --ingroup $GROUP_NAME --home /app/webapp $USER_NAME
#<USERGROUP-INJECTION-POINT>
# Run chown regardess of the previous step
RUN chown -R $USER_NAME:$GROUP_NAME /app/webapp/

COPY ./startup.sh /app/webapp/
RUN chmod +x /app/webapp/startup.sh
ENV OTEL_DOTNET_AUTO_HOME=${OTEL_DOTNET_AUTO_HOME}
ENV DOTNET_OPTS=${DOTNET_OPTS}
ENV APM_OPTS=${APM_OPTS}

USER $USER_NAME

EXPOSE 8080
ENTRYPOINT ["/app/webapp/startup.sh"]

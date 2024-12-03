#!/bin/sh

# Start the nodejs server in foreground
cd /app/webapp
$JAVA_HOME/bin/java $JAVA_OPTS $APM_OPTS -jar /app/webapp/app.jar
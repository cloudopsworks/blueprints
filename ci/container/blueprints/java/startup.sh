#!/bin/sh

# Start the nodejs server in foreground
cd /app/webapp
$JAVA_HOME/bin/java -XX:+UnlockExperimentalVMOptions $JAVA_OPTS $APM_OPTS -jar /app/webapp/app.jar
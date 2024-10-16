export PROJECT ?= $(shell basename $(shell pwd))
TRONADOR_AUTO_INIT := true

-include $(shell curl -sSL -o .tronador "https://cowk.io/acc"; echo .tronador)

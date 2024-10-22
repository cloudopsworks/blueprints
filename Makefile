##
# (c) 2024 - Cloud Ops Works LLC - https://cloudops.works/
#            On GitHub: https://github.com/cloudopsworks
#            Distributed Under Apache v2.0 License
#
PWD := $(shell pwd)
CURR := $(shell basename $(PWD))
DATE :=	$(shell date +%Y%m%d-%H%M%S.%s)
VER_NUM := $(shell cat .github/_VERSION)
VER_MAJOR := $(shell echo $(VER_NUM) | cut -f1 -d.)
VER_MINOR := $(shell echo $(VER_NUM) | cut -f2 -d.)
VER_PATCH := $(shell echo $(VER_NUM) | cut -f3 -d.)

export PROJECT ?= $(shell basename $(shell pwd))
TRONADOR_AUTO_INIT := true

-include $(shell curl -sSL -o .tronador "https://cowk.io/acc"; echo .tronador)

## Lint the code
lint:
	terragrunt --terragrunt-workging-dir terraform/ run-all hclfmt

.PHONY: tag
.PHONY: tag_local
.PHONY: version

co_master:
	git checkout master

tag_local: co_master
	git tag -f $(VER_MAJOR).$(VER_MINOR)
	git tag -f $(VER_MAJOR)

## Tag the current version
tag: tag_local
	git push origin -f $(VER_MAJOR).$(VER_MINOR)
	git push origin -f $(VER_MAJOR)
	git switch -

## Update generate the version
version: gitflow/version/file

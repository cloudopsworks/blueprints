##
# (c) 2021-2025
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#
SHELL := /bin/bash
TRONADOR_AUTO_INIT := true
GITVERSION ?= $(INSTALL_PATH)/gitversion

# List of targets the `readme` target should call before generating the readme
export README_DEPS ?= docs/targets.md docs/terraform.md

-include $(shell curl -sSL -o .tronador "https://cowk.io/acc"; echo .tronador)


get_version: packages/install/gitversion
	$(call assert-set,GITVERSION)
	$(eval VER_NUM := v$(shell $(GITVERSION) -output json -showvariable MajorMinorPatch))
	$(eval VER_MAJOR := $(shell echo $(VER_NUM) | cut -f1 -d.))
	$(eval VER_MINOR := $(shell echo $(VER_NUM) | cut -f2 -d.))
	$(eval VER_PATCH := $(shell echo $(VER_NUM) | cut -f3 -d.))

co_master:
	git checkout master

tag_local: get_version
	git tag -f $(VER_MAJOR).$(VER_MINOR)

tag_local_all: get_version
	git tag -f $(VER_MAJOR).$(VER_MINOR)
	git tag -f $(VER_MAJOR)

## Tag the current version only upto minor
tag:: co_master tag_local
	git push origin -f $(VER_MAJOR).$(VER_MINOR)
	git checkout develop

## Tag the current version upto major and minor
tagall:: co_master tag_local_all
	git push origin -f $(VER_MAJOR).$(VER_MINOR)
	git push origin -f $(VER_MAJOR)
	git checkout develop

## Tag the current support branch (no master checkout
tagbranch:: tag_local
	git push origin -f $(VER_MAJOR).$(VER_MINOR)

# Build the current branch as hotfix and merge it into develop and master
build-hotfix:
	@$(MAKE) gitflow/hotfix/start
	@$(MAKE) gitflow/hotfix/publish
	@git merge develop
	@$(MAKE) gitflow/version/file
	@$(MAKE) gitflow/hotfix/finish/local
	@git checkout develop
	@git merge master --no-ff
	@git push
	@$(MAKE) tag
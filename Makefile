SHELL := /bin/bash
TRONADOR_AUTO_INIT := true
GITVERSION ?= $(INSTALL_PATH)/gitversion
define PROVIDER_CHOMP
provider "aws" {
  alias = "default"
}
provider "aws" {
  alias = "account"
}
endef
export PROVIDER_CHOMP

# List of targets the `readme` target should call before generating the readme
export README_DEPS ?= docs/targets.md docs/terraform.md

-include $(shell curl -sSL -o .tronador "https://cowk.io/acc"; echo .tronador)

temp_provider:
	echo "$$PROVIDER_CHOMP" > provider.temp.tf

## Lint terraform/opentofu code
lint: temp_provider
	$(SELF) tofu/install tofu/get-modules tofu/get-plugins tofu/lint tofu/validate

# Format terraform/opentofu code
fmt:
	$(SELF) tofu/install tofu/fmt


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
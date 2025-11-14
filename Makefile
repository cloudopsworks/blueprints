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
PROVIDER ?= $(shell cat .cloudopsworks/.provider 2>/dev/null || echo "aws")
define PROVIDER_CHOMP_AWS
provider "aws" {
  alias = "default"
}
provider "aws" {
  alias = "account"
}
endef
define PROVIDER_CHOMP_GCP
provider "google" {
}
provider "google-beta" {
}
endef
define PROVIDER_CHOMP_AZURERM
provider "azurerm" {
  features {}
}
endef
export PROVIDER_CHOMP_AWS
export PROVIDER_CHOMP_GCP
export PROVIDER_CHOMP_AZURERM

# List of targets the `readme` target should call before generating the readme
export README_DEPS ?= docs/targets.md docs/terraform.md

-include $(shell curl -sSL -o .tronador "https://cowk.io/acc"; echo .tronador)

temp_provider:
ifeq ($(PROVIDER),gcp)
	echo "$$PROVIDER_CHOMP_GCP" > provider.temp.tf
else ifeq ($(PROVIDER),aws)
	echo "$$PROVIDER_CHOMP_AWS" > provider.temp.tf
else ifeq ($(PROVIDER),azurerm)
	echo "$$PROVIDER_CHOMP_AZURERM" > provider.temp.tf
else
	@echo "No valid provider specified. Please set the PROVIDER variable to 'aws' or 'gcp'."
	@exit 1
endif

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

tag_local: co_master get_version
	git tag -f $(VER_MAJOR).$(VER_MINOR)
	git tag -f $(VER_MAJOR)

## Tag the current version
tag:: tag_local
	git push origin -f $(VER_MAJOR).$(VER_MINOR)
	git push origin -f $(VER_MAJOR)
	git checkout develop

## Initialize the project for a specific cloud provider: AWS
init/aws:
	@echo -n "aws" > .cloudopsworks/.provider
	@rm -f provider.temp.tf
	@cp .cloudopsworks/boilerplate/aws/* .
	@$(GIT) add .cloudopsworks/.provider *.tf

## Initialize the project for a specific cloud provider: GCP
init/gcp:
	@echo -n "gcp" > .cloudopsworks/.provider
	@rm -f provider.temp.tf
	@cp .cloudopsworks/boilerplate/gcp/* .
	@$(GIT) add .cloudopsworks/.provider *.tf

## Initialize the project for a specific cloud provider: Azure RM
init/azurerm:
	@echo -n "azurerm" > .cloudopsworks/.provider
	@rm -f provider.temp.tf
	@cp .cloudopsworks/boilerplate/azurerm/* .
	@$(GIT) add .cloudopsworks/.provider *.tf
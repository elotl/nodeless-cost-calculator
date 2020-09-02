NAME=nodeless-cost-calculator

REGISTRY_REPO ?= elotl/$(NAME)

DKR=docker

GIT_VERSION=$(shell git describe --dirty)
CURRENT_TIME=$(shell date +%Y%m%d%H%M%S)
IMAGE_TAG=$(GIT_VERSION)
ifneq ($(findstring -,$(GIT_VERSION)),)
IMAGE_DEV_OR_LATEST=dev
else
IMAGE_DEV_OR_LATEST=latest
endif

img:
	@echo "Checking if IMAGE_TAG is set" && test -n "$(IMAGE_TAG)"
	$(DKR) build -t $(REGISTRY_REPO):$(IMAGE_TAG) \
	 	-t $(REGISTRY_REPO):$(IMAGE_DEV_OR_LATEST) .

login-img:
	@echo "Checking if REGISTRY_USER is set" && test -n "$(REGISTRY_USER)"
	@echo "Checking if REGISTRY_PASSWORD is set" && test -n "$(REGISTRY_PASSWORD)"
	@$(DKR) login -u "$(REGISTRY_USER)" -p "$(REGISTRY_PASSWORD)" "$(REGISTRY_SERVER)"

push-img: img
	@echo "Checking if IMAGE_TAG is set" && test -n "$(IMAGE_TAG)"
	$(DKR) push $(REGISTRY_REPO):$(IMAGE_TAG)
	$(DKR) push $(REGISTRY_REPO):$(IMAGE_DEV_OR_LATEST)

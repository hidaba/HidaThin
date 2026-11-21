CC ?= gcc
PKG_CONFIG ?= pkg-config

PKGS = freerdp3 freerdp-client3 winpr3 x11 xext
CFLAGS_PKGS := $(shell $(PKG_CONFIG) --cflags $(PKGS))
LIBS_PKGS := $(shell $(PKG_CONFIG) --libs $(PKGS)) -lXcursor -lm -lpthread

CFLAGS ?= -O3 -ffast-math -ftree-vectorize -funroll-loops -Wall -Wextra -Wno-unused-parameter -Wno-deprecated-declarations
ifeq ($(shell uname -m),aarch64)
    CFLAGS += -mcpu=native
endif

TARGET = hidathin-rdp
SRC = hidathin_rdp.c

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) $(CFLAGS_PKGS) -o $(TARGET) $(SRC) $(LIBS_PKGS)

install: $(TARGET)
	install -m 0755 $(TARGET) /usr/local/bin/$(TARGET)

clean:
	rm -f $(TARGET) *.o

.PHONY: all install clean

CC      = gcc
CFLAGS  = -shared -fPIC
LDFLAGS = -lcryptopp

all: CoreFoundation.so libOSXWindowManagement.so libblz_commerce_sdk_plugin.so

CoreFoundation.so: CoreFoundation.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

libOSXWindowManagement.so: OSXWindowManagement.c
	$(CC) $(CFLAGS) -o $@  $<

libblz_commerce_sdk_plugin.so: blz_commerce_sdk_plugin.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f *.so

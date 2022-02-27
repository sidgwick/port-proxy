#!/bin/bash

package=pproxy_0.0.1

if [ -d $pproxy ]; then
	rm -rf $pproxy
fi

mkdir $package

cp -r DEBIAN lib $package
mkdir -p $package/{usr/bin,etc/pproxy}

cp ../main.py $package/usr/bin/pproxy
cp ../{client,server}.yaml $package/etc/pproxy

chmod 0755 $package/DEBIAN/{preinst,prerm,postinst,postrm}
chmod a+x $package/usr/bin/*

dpkg-deb --build --root-owner-group $package

rm -rf $package


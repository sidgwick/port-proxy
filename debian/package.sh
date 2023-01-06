#!/bin/bash

package=pproxy_0.0.1

if [ -d $pproxy ]; then
	rm -rf $pproxy
fi

mkdir $package

cp -r DEBIAN lib $package
mkdir -p $package/{usr/bin,etc/pproxy,usr/lib/pproxy}

cat << EO_ENTRY > $package/usr/bin/pproxy
#!/bin/bash

python /usr/lib/pproxy/app.py $@
EO_ENTRY

cp ../{client,server}.yaml $package/etc/pproxy
cp -r ../app.py ../src $package/lib/pproxy

chmod 0755 $package/DEBIAN/{preinst,prerm,postinst,postrm}
chmod a+x $package/usr/bin/*

dpkg-deb --build --root-owner-group $package

rm -rf $package


"""
Builds non-live bootable CD's that have PXE-equivalent behavior
for all cobbler profiles currently in memory.

Copyright 2006-2009, Red Hat, Inc
Michael DeHaan <mdehaan@redhat.com>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301  USA
"""

import os
import os.path
import shutil
import sys
import traceback
import shutil
import re

import utils
from cexceptions import *
from utils import _
import clogger

class BuildIso:
    """
    Handles conversion of internal state to the tftpboot tree layout
    """

    def __init__(self,config,verbose=False,logger=None):
        """
        Constructor
        """
        self.verbose     = verbose
        self.config      = config
        self.settings    = config.settings()
        self.api         = config.api
        self.distros     = config.distros()
        self.profiles    = config.profiles()
        self.systems     = config.systems()
        self.distros     = config.distros()
        self.distmap     = {}
        self.distctr     = 0
        self.source      = ""
        if logger is None:
            logger       = clogger.Logger()
        self.logger      = logger
        # grab the header from buildiso.header file
        header_src = open(os.path.join(self.settings.iso_template_dir,"buildiso.header"))
        self.iso_template = header_src.read()
        header_src.close()


    def make_shorter(self,distname):
        if self.distmap.has_key(distname):
            return self.distmap[distname]
        else:
            self.distctr = self.distctr + 1
            self.distmap[distname] = str(self.distctr)
            return str(self.distctr)

  
    def generate_netboot_iso(self,imagesdir,isolinuxdir,profiles=[],systems=[],exclude_dns=None):
       # function to sort profiles/systems by name
       def sort_name(a,b):
           return cmp(a.name,b.name)

       # handle profile selection override provided via commandline (default is all)
       all_profiles = [profile for profile in self.api.profiles()]
       all_profiles.sort(sort_name)
       which_profiles = utils.input_string_or_list(profiles)

       # handle system selection override provided via commandline (default is all)
       all_systems = [system for system in self.api.systems()]
       all_systems.sort(sort_name)
       which_systems = utils.input_string_or_list(systems)

       # no systems and profiles are selected, so let's select all
       # only possible from the cli: cobbler buildiso
       want_all_systems = False
       if len(which_systems) == 0 and len(which_profiles) == 0:
          want_all_systems = True

       # include profiles for selected systems only
       for system in all_systems:
          if want_all_systems == True:
             which_systems.append(system.name)
          if system.name in which_systems:
             profile = system.get_conceptual_parent()
             if profile.name not in which_profiles:
                which_profiles.append(profile.name)

       # setup isolinux.cfg
       isolinuxcfg = os.path.join(isolinuxdir, "isolinux.cfg")
       cfg = open(isolinuxcfg, "w+")
       cfg.write(self.iso_template)

       # iterate through selected profiles
       for profile in all_profiles:
          if profile.name in which_profiles:
             self.logger.info("processing profile: %s" % profile.name)
             dist = profile.get_conceptual_parent()
             distname = self.make_shorter(dist.name)
             # buildisodir/isolinux/$distro/vmlinuz, initrd.img
             # FIXME: this will likely crash on non-Linux breeds
             f1 = os.path.join(isolinuxdir, "%s.krn" % distname)
             f2 = os.path.join(isolinuxdir, "%s.img" % distname)
             if not os.path.exists(dist.kernel):
                 utils.die(self.logger,"path does not exist: %s" % dist.kernel)
             if not os.path.exists(dist.initrd):
                 utils.die(self.logger,"path does not exist: %s" % dist.initrd)
             shutil.copyfile(dist.kernel, f1)
             shutil.copyfile(dist.initrd, f2)

             cfg.write("\n")
             cfg.write("LABEL %s\n" % profile.name)
             cfg.write("  MENU LABEL %s\n" % profile.name)
             cfg.write("  kernel %s.krn\n" % distname)

             data = utils.blender(self.api, True, profile)
             if data["kickstart"].startswith("/"):
                 data["kickstart"] = "http://%s:%s/cblr/svc/op/ks/profile/%s" % (
                     data["server"], self.api.settings().http_port, profile.name
                 )

             append_line = " append initrd=%s.img" % distname
             if dist.breed == "suse":
                 append_line += " autoyast=%s" % data["kickstart"]
             if dist.breed == "redhat":
                 append_line += " ks=%s" % data["kickstart"]
             if dist.breed in ["ubuntu","debian"]:
                 append_line += " auto-install/enable=true url=%s" % data["kickstart"]
             append_line = append_line + " %s\n" % data["kernel_options"]
             cfg.write(append_line)

             length=len(append_line)
             if length > 254:
                self.logger.warning("append line length is greater than 254 chars (%s chars)" % length)

       cfg.write("\nMENU SEPARATOR\n")

       # iterate through all selected systems
       for system in all_systems:
          if system.name in which_systems:
             self.logger.info("processing system: %s" % system.name)
             profile = system.get_conceptual_parent()
             dist = profile.get_conceptual_parent()
             distname = self.make_shorter(dist.name)
             # buildisodir/isolinux/$distro/vmlinuz, initrd.img
             # FIXME: this will likely crash on non-Linux breeds
             if not os.path.exists(dist.kernel) or not os.path.exists(dist.initrd):
                shutil.copyfile(dist.kernel, os.path.join(isolinuxdir, "%s.krn" % distname))
                shutil.copyfile(dist.initrd, os.path.join(isolinuxdir, "%s.img" % distname))

             cfg.write("\n")
             cfg.write("LABEL %s\n" % system.name)
             cfg.write("  MENU LABEL %s\n" % system.name)
             cfg.write("  kernel %s.krn\n" % distname)

             bdata = utils.blender(self.api, True, system)
             if bdata["kickstart"].startswith("/"):
                 bdata["kickstart"] = "http://%s:%s/cblr/svc/op/ks/system/%s" % (
                     bdata["server"], self.api.settings().http_port, system.name
                 )

             append_line = " append initrd=%s.img" % distname
             if dist.breed == "suse":
                append_line += " autoyast=%s" % bdata["kickstart"]
             if dist.breed == "redhat":
                append_line += " ks=%s" % bdata["kickstart"]
             if dist.breed in ["ubuntu","debian"]:
                append_line += " auto-install/enable=true url=%s netcfg/disable_dhcp=true" % bdata["kickstart"]
                # hostname is required as a parameter, the one in the preseed is not respected
                my_domain = "local.lan"
                if system.hostname != "":
                    # if this is a FQDN, grab the first bit
                    my_hostname = system.hostname.split(".")[0]
                    _domain = system.hostname.split(".")[1:]
                    if _domain:
                       my_domain = ".".join(_domain)
                else:
                    my_hostname = system.name.split(".")[0]
                    _domain = system.name.split(".")[1:]
                    if _domain:
                       my_domain = ".".join(_domain)
                # at least for debian deployments configured for DHCP networking
                # this values are not used, but specifying here avoids questions
                append_line += " hostname=%s domain=%s" % (my_hostname, my_domain)
                # a similar issue exists with suite name, as installer requires
                # the existence of "stable" in the dists directory
                append_line += " suite=%s" % dist.os_version

             # try to add static ip boot options to avoid DHCP (interface/ip/netmask/gw/dns)
             # check for overrides first and clear them from kernel_options
             data = utils.blender(self.api, False, system) # don't collapse!
             my_int = None;  my_ip = None; my_mask = None; my_gw = None; my_dns = None
             if dist.breed in ["suse", "redhat"]:
                if data["kernel_options"].has_key("netmask") and data["kernel_options"]["netmask"] != "":
                   my_mask = data["kernel_options"]["netmask"]
                   del data["kernel_options"]["netmask"]
                if data["kernel_options"].has_key("gateway") and data["kernel_options"]["gateway"] != "":
                   my_gw = data["kernel_options"]["gateway"]
                   del data["kernel_options"]["gateway"]

             if dist.breed == "redhat":
                if data["kernel_options"].has_key("ksdevice") and data["kernel_options"]["ksdevice"] != "":
                   my_int = data["kernel_options"]["ksdevice"]
                   del data["kernel_options"]["ksdevice"]
                if data["kernel_options"].has_key("ip") and data["kernel_options"]["ip"] != "":
                   my_ip = data["kernel_options"]["ip"]
                   del data["kernel_options"]["ip"]
                if data["kernel_options"].has_key("dns") and data["kernel_options"]["dns"] != "":
                   my_dns = data["kernel_options"]["dns"]
                   del data["kernel_options"]["dns"]

             if dist.breed == "suse":
                if data["kernel_options"].has_key("netdevice") and data["kernel_options"]["netdevice"] != "":
                   my_int = data["kernel_options"]["netdevice"]
                   del data["kernel_options"]["netdevice"]
                if data["kernel_options"].has_key("hostip") and data["kernel_options"]["hostip"] != "":
                   my_ip = data["kernel_options"]["hostip"]
                   del data["kernel_options"]["hostip"]
                if data["kernel_options"].has_key("nameserver") and data["kernel_options"]["nameserver"] != "":
                   my_dns = data["kernel_options"]["nameserver"]
                   del data["kernel_options"]["nameserver"]

             if dist.breed in ["ubuntu","debian"]:
                if data["kernel_options"].has_key("netcfg/choose_interface") and data["kernel_options"]["netcfg/choose_interface"] != "":
                   my_int = data["kernel_options"]["netcfg/choose_interface"]
                   del data["kernel_options"]["netcfg/choose_interface"]
                if data["kernel_options"].has_key("netcfg/get_ipaddress") and data["kernel_options"]["netcfg/get_ipaddress"] != "":
                   my_ip = data["kernel_options"]["netcfg/get_ipaddress"]
                   del data["kernel_options"]["netcfg/get_ipaddress"]
                if data["kernel_options"].has_key("netcfg/get_netmask") and data["kernel_options"]["netcfg/get_netmask"] != "":
                   my_mask = data["kernel_options"]["netcfg/get_netmask"]
                   del data["kernel_options"]["netcfg/get_netmask"]
                if data["kernel_options"].has_key("netcfg/get_gateway") and data["kernel_options"]["netcfg/get_gateway"] != "":
                   my_gw = data["kernel_options"]["netcfg/get_gateway"]
                   del data["kernel_options"]["netcfg/get_gateway"]
                if data["kernel_options"].has_key("netcfg/get_nameservers") and data["kernel_options"]["netcfg/get_nameservers"] != "":
                   my_dns = data["kernel_options"]["netcfg/get_nameservers"]
                   del data["kernel_options"]["netcfg/get_nameservers"]

             # if no kernel_options overrides are present find the management interface
             # do nothing when zero or multiple management interfaces are found
             if my_int is None:
                mgmt_ints = []; mgmt_ints_multi = []; slave_ints = []
                if len(data["interfaces"].keys()) >= 1:
                   for (iname, idata) in data["interfaces"].iteritems():
                      if idata["management"] == True and idata["interface_type"] in ["master","bond","bridge"]:
                         # bonded/bridged management interface
                         mgmt_ints_multi.append(iname)
                      if idata["management"] == True and idata["interface_type"] not in ["master","bond","bridge","slave","bond_slave","bridge_slave"]:
                         # single management interface
                         mgmt_ints.append(iname)

                if len(mgmt_ints_multi) == 1 and len(mgmt_ints) == 0:
                   # bonded/bridged management interface, find a slave interface
                   # if eth0 is a slave use that (it's what people expect)
                   for (iname, idata) in data["interfaces"].iteritems():
                      if idata["interface_type"] in ["slave","bond_slave","bridge_slave"] and idata["interface_master"] == mgmt_ints_multi[0]:
                         slave_ints.append(iname)

                   if "eth0" in slave_ints:
                      my_int = "eth0"
                   else:
                      my_int = slave_ints[0]
                   # set my_ip from the bonded/bridged interface here
                   my_ip = data["ip_address_" + data["interface_master_" + my_int]]
                   my_mask = data["netmask_" + data["interface_master_" + my_int]]

                if len(mgmt_ints) == 1 and len(mgmt_ints_multi) == 0:
                   # single management interface
                   my_int = mgmt_ints[0]

             # lookup tcp/ip configuration data
             if my_ip is None and my_int is not None:
                if data.has_key("ip_address_" + my_int) and data["ip_address_" + my_int] != "":
                   my_ip = data["ip_address_" + my_int]

             if my_mask is None and my_int is not None:
                if data.has_key("netmask_" + my_int) and data["netmask_" + my_int] != "":
                   my_mask = data["netmask_" + my_int]

             if my_gw is None:
                if data.has_key("gateway") and data["gateway"] != "":
                   my_gw = data["gateway"]

             if my_dns is None:
                if data.has_key("name_servers") and data["name_servers"] != "":
                   my_dns = data["name_servers"]
             
             # add information to the append_line
             if my_int is not None:
                 if dist.breed == "suse":
                     if data.has_key("mac_address_" + my_int) and data["mac_address_" + my_int] != "":
                        append_line += " netdevice=%s" % data["mac_address_" + my_int]
                     else:
                        append_line += " netdevice=%s" % my_int
                 if dist.breed == "redhat":
                     if data.has_key("mac_address_" + my_int) and data["mac_address_" + my_int] != "":
                        append_line += " ksdevice=%s" % data["mac_address_" + my_int]
                     else:
                        append_line += " ksdevice=%s" % my_int
                 if dist.breed in ["ubuntu","debian"]:
                     append_line += " netcfg/choose_interface=%s" % my_int

             if my_ip is not None:
                 if dist.breed == "suse":
                     append_line += " hostip=%s" % my_ip
                 if dist.breed == "redhat":
                     append_line += " ip=%s" % my_ip
                 if dist.breed in ["ubuntu","debian"]:
                     append_line += " netcfg/get_ipaddress=%s" % my_ip

             if my_mask is not None:
                 if dist.breed in ["suse","redhat"]:
                     append_line += " netmask=%s" % my_mask
                 if dist.breed in ["ubuntu","debian"]:
                     append_line += " netcfg/get_netmask=%s" % my_mask

             if my_gw is not None:
                 if dist.breed in ["suse","redhat"]:
                     append_line += " gateway=%s" % my_gw
                 if dist.breed in ["ubuntu","debian"]:
                     append_line += " netcfg/get_gateway=%s" % my_gw

             if exclude_dns is None or my_dns is not None:
                if dist.breed == "suse":
                   append_line += " nameserver=%s" % my_dns[0]
                if dist.breed == "redhat":
                   append_line += " dns=%s" % ",".join(my_dns)
                if dist.breed in ["ubuntu","debian"]:
                   append_line += " netcfg/get_nameservers=%s" % ",".join(my_dns)

             # add remaining kernel_options to append_line
             for (k, v) in data["kernel_options"].iteritems():
                if v == None:
                   append_line += " %s" % k
                else:
                   append_line += " %s=%s" % (k,v)
             append_line += "\n"
             cfg.write(append_line)

             length = len(append_line)
             if length > 254:
                self.logger.warning("append line length is greater than 254 chars (%s chars)" % length)

       cfg.write("\n")
       cfg.write("MENU END\n")
       cfg.close()


    def generate_standalone_iso(self,imagesdir,isolinuxdir,distname,filesource):

        # Get the distro object for the requested distro
        # and then get all of its descendants (profiles/sub-profiles/systems)
        distro = self.api.find_distro(distname)
        if distro is None:
            utils.die(self.logger,"distro %s was not found, aborting" % distname)
        descendants = distro.get_descendants()

        if filesource is None:
            # Try to determine the source from the distro kernel path
            self.logger.debug("trying to locate source for distro")
            found_source = False
            (source_head, source_tail) = os.path.split(distro.kernel)
            while source_tail != '':
                if source_head == os.path.join(self.api.settings().webdir, "ks_mirror"):
                    filesource = os.path.join(source_head, source_tail)
                    found_source = True
                    self.logger.debug("found source in %s" % filesource)
                    break
                (source_head, source_tail) = os.path.split(source_head)
            # Can't find the source, raise an error
            if not found_source:
                utils.die(self.logger," Error, no installation source found. When building a standalone ISO, you must specify a --source if the distro install tree is not hosted locally")

        self.logger.info("copying kernels and initrds for standalone distro")
        # buildisodir/isolinux/$distro/vmlinuz, initrd.img
        # FIXME: this will likely crash on non-Linux breeds
        f1 = os.path.join(isolinuxdir, "vmlinuz")
        f2 = os.path.join(isolinuxdir, "initrd.img")
        if not os.path.exists(distro.kernel):
            utils.die(self.logger,"path does not exist: %s" % distro.kernel)
        if not os.path.exists(distro.initrd):
            utils.die(self.logger,"path does not exist: %s" % distro.initrd)
        shutil.copyfile(distro.kernel, f1)
        shutil.copyfile(distro.initrd, f2)

        cmd = "rsync -rlptgu --exclude=boot.cat --exclude=TRANS.TBL --exclude=isolinux/ %s/ %s/../" % (filesource, isolinuxdir)
        self.logger.info("- copying distro %s files (%s)" % (distname,cmd))
        rc = utils.subprocess_call(self.logger, cmd, shell=True)
        if rc:
            utils.die(self.logger,"rsync of files failed")

        self.logger.info("generating a isolinux.cfg")
        isolinuxcfg = os.path.join(isolinuxdir, "isolinux.cfg")
        cfg = open(isolinuxcfg, "w+")
        cfg.write(self.iso_template)

        for descendant in descendants:
            data = utils.blender(self.api, True, descendant)

            cfg.write("\n")
            cfg.write("LABEL %s\n" % descendant.name)
            cfg.write("  MENU LABEL %s\n" % descendant.name)
            cfg.write("  kernel vmlinuz\n")

            data["kickstart"] = "cdrom:/isolinux/ks-%s.cfg" % descendant.name

            append_line = "  append initrd=initrd.img"
            append_line = append_line + " ks=%s " % data["kickstart"]
            append_line = append_line + " %s\n" % data["kernel_options"]

            cfg.write(append_line)

            if descendant.COLLECTION_TYPE == 'profile':
                kickstart_data = self.api.kickgen.generate_kickstart_for_profile(descendant.name)
            elif descendant.COLLECTION_TYPE == 'system':
                kickstart_data = self.api.kickgen.generate_kickstart_for_system(descendant.name)

            cdregex = re.compile("url .*\n", re.IGNORECASE)
            kickstart_data = cdregex.sub("cdrom\n", kickstart_data)

            ks_name = os.path.join(isolinuxdir, "ks-%s.cfg" % descendant.name)
            ks_file = open(ks_name, "w+")
            ks_file.write(kickstart_data)
            ks_file.close()

        self.logger.info("done writing config")
        cfg.write("\n")
        cfg.write("MENU END\n")
        cfg.close()

        return


    def run(self,iso=None,buildisodir=None,profiles=None,systems=None,distro=None,standalone=None,source=None,exclude_dns=None):

        # the distro option is for stand-alone builds only
        if not standalone and distro is not None:
            utils.die(self.logger,"The --distro option should only be used when creating a standalone ISO")
        # if building standalone, we only want --distro,
        # profiles/systems are disallowed
        if standalone:
            if profiles is not None or systems is not None:
                utils.die(self.logger,"When building a standalone ISO, use --distro only instead of --profiles/--systems")
            elif distro is None:
                utils.die(self.logger,"When building a standalone ISO, you must specify a --distro")
            if source != None and not os.path.exists(source):
                utils.die(self.logger,"The source specified (%s) does not exist" % source)

        # if iso is none, create it in . as "kickstart.iso"
        if iso is None:
            iso = "kickstart.iso"

        if buildisodir is None:
            buildisodir = self.settings.buildisodir
        else:
            if not os.path.isdir(buildisodir):
                utils.die(self.logger,"The --tempdir specified is not a directory")

            (buildisodir_head,buildisodir_tail) = os.path.split(os.path.normpath(buildisodir))
            if buildisodir_tail != "buildiso":
                buildisodir = os.path.join(buildisodir, "buildiso")

        self.logger.info("using/creating buildisodir: %s" % buildisodir)
        if not os.path.exists(buildisodir):
            os.makedirs(buildisodir)
        else:
            shutil.rmtree(buildisodir)
            os.makedirs(buildisodir)

        # if base of buildisodir does not exist, fail
        # create all profiles unless filtered by "profiles"

        imagesdir = os.path.join(buildisodir, "images")
        isolinuxdir = os.path.join(buildisodir, "isolinux")

        self.logger.info("building tree for isolinux")
        if not os.path.exists(imagesdir):
            os.makedirs(imagesdir)
        if not os.path.exists(isolinuxdir):
            os.makedirs(isolinuxdir)

        self.logger.info("copying miscellaneous files")

        isolinuxbin = "/usr/share/syslinux/isolinux.bin"
        if not os.path.exists(isolinuxbin):
            isolinuxbin = "/usr/lib/syslinux/isolinux.bin"

        menu = "/usr/share/syslinux/menu.c32"
        if not os.path.exists(menu):
            menu = "/var/lib/cobbler/loaders/menu.c32"

        chain = "/usr/share/syslinux/chain.c32"
        if not os.path.exists(chain):
            chain = "/usr/lib/syslinux/chain.c32"

        files = [ isolinuxbin, menu, chain ]
        for f in files:
            if not os.path.exists(f):
               utils.die(self.logger,"Required file not found: %s" % f)
            else:
               utils.copyfile(f, os.path.join(isolinuxdir, os.path.basename(f)), self.api)

        if standalone:
            self.generate_standalone_iso(imagesdir,isolinuxdir,distro,source)
        else:
            self.generate_netboot_iso(imagesdir,isolinuxdir,profiles,systems,exclude_dns)

        # removed --quiet
        cmd = "mkisofs -o %s -r -b isolinux/isolinux.bin -c isolinux/boot.cat" % iso
        cmd = cmd + " -no-emul-boot -boot-load-size 4"
        cmd = cmd + " -boot-info-table -V Cobbler\ Install -R -J -T %s" % buildisodir

        rc = utils.subprocess_call(self.logger, cmd, shell=True)
        if rc != 0:
            utils.die(self.logger,"mkisofs failed")

        self.logger.info("ISO build complete")
        self.logger.info("You may wish to delete: %s" % buildisodir)
        self.logger.info("The output file is: %s" % iso)

        return True



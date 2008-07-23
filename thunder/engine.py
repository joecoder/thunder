#!/usr/bin/env python
# stdlib imports
import os,  sys,  re
import time,  random
import types, popen2
# thunder imports
import slurp, net
import event

class Engine:
	def __init__(self):
		self.DEBUG = False ; self.watcher = event.Watcher()
		self.partitions = {} ; self.th_vars = []
		self.host_cmds = [] ; self.chroot_cmds = []
		self.slurp = slurp.Proc() ; self.handler_map = [
			('^debug.*', self._toggleDebug),
			('^set.*', self.setVar), ('^detect-disks.*', self.detectDisks),
			('^clear-partitions.*', self.clearPartitions),
			('^partition-disk.*', self.partitionDisk),	
			('^commit-partitions.*', self.commitPartitions),
			('^format-partition.*', self.formatPartition),
			('^mount-partition.*', self.mountPartition),
			('^swapon.*', self.swapOn), ('^exec-command.*', self.execCommand),
			('^fetch.*', self.fetchUri),
			('^fetch-and-extract.*', self.fetchAndExtract),
			('^chroot-command.*', self.chrootCommand),
			('^chroot-batch.*', self.chrootBatch)
		]
		for i in self.handler_map:
				if self.DEBUG == True: self.watcher.logEvent('debug', 'adding callback %s with pattern %s' % (repr(i[1]),i[0]))
				self.slurp.register_trigger(args={'t_pattern': i[0], 't_callback': i[1]})

	def setVar(self, txt):
		if type(txt) != types.StringType and txt != '':
			tmp = txt.split()
			self.th_vars.append((tmp[1], tmp[2]))
			if self.DEBUG == True: self.watcher.logEvent('debug', 'Setting key %s to value %s' % (tmp[1], tmp[2]))
			self.watcher.logEvent('events', txt.strip()+'\n')
			return True
		else:	return False
	
	def detectDisks(self, txt):
		if type(txt) == types.StringTYpe and txt != '':
			self.watcher.logEvent('events', txt.strip()+'\n')
			tmp_dsks = []
			for i in os.listdir('/dev/'):
				if i.find('hd') != -1 or i.find('sd') != -1:
					if len(i) == 3: tmp_dsks.append(i)
			self.th_disks = tmp_dsks
			self.th_disks.sort()
			line = txt.split()
			line.pop(0)
			for i in range(len(line)):
				if line[i] == 'prefer':
					prefer = line[(i+1)]
				if line[i] == 'accept':
					accept = line[(i+1)]
			pref_tmp = []
			acpt_tmp = []
			for i in self.th_disks:
				if i.find(prefer) != -1:
					pref_tmp.append(i)
				if i.find(accept) != -1:
					acpt_tmp.append(i)
			self.disks = []
			pref_tmp.sort()
			acpt_tmp.sort()
			for a in (pref_tmp, acpt_tmp):
				for b in a:
					self.disks.append(b)
			cnt=0
			for i in self.disks:
				self.th_vars.append(('drive%d' % cnt, '/dev/%s' % i))
				if self.DEBUG == True: self.watcher.logEvent('debug', 'Setting key drive%d to value /dev/%s' % (cnt,i))
				self.partitions[i] = []
				cnt += 1
			return True
		else: return False

	def clearPartitions(self, txt):
		if type(txt) == types.StringType and txt != '':
			tmp = self._chkSubs(txt)
			self.watcher.logEvent('events', txt)
			line = tmp.split()
			disk = line[1]
			self._execCmd('dd if=/dev/zero of=%s bs=512K count=1' % disk)
			return True
		else: return False

	def partitionDisk(self, txt):
		if type(txt) == types.StringType and txt != '':
			tmp = self._chkSubs(txt)
			self.watcher.logEvent('events', txt)
			opts = tmp.split()
			dev = opts[1]
			type = opts[2]
			if type == 'primary' or type == 'logical':
				pnum = opts[3]
				pnam = opts[4]
				if opts[5] != 'all': psze = opts[5]
				if opts[5] == 'all': psze = ''
				ptyp = opts[6]
				self.th_vars.append((pnam, '%s%s' % (dev,pnum)))
				if self.DEBUG == True: self.watcher.logEvent('debug', 'Setting key %s to value %s%s' % (pnam,dev,pnum))
				self.partitions[os.path.basename(dev)].append(',%s,%s' % (psze,ptyp))
			elif type == 'extended':
				if opts[3] != 'all': psze = opts[3]
				else: psze = ''
				self.partitions[os.path.basename(dev)].append(',%s,E' % psze)
			return True
		else: return False


class Thunder:
	def commit_partitions(self, txt):
		kys = self.partitions.keys()
		kys.sort()
		for i in kys:
			if self.partitions[i] != []:
				sys.stdout.write('[ ] Partitioning %s' % i)
				sys.stdout.flush()
				fp = open('/tmp/partitions', 'w+')
				for b in self.partitions[i]:
					fp.write(b+'\n')
				fp.close()
				self._exec_cmd('cat /tmp/partitions | /sbin/sfdisk -uM /dev/%s' % i)
				sys.stdout.write('\r[+]')
				print ''
		return

	def format_partition(self, txt):
		line = self._chk_subs(txt).split()
		line.pop(0)
		part = line[0]
		labl = line[1].upper()
		type = line[2]
		for i in [1,2,3]: line.pop(0)
		if len(line) > 0:
			args = ''
			for i in line:
				args = args+i+' '
			t = re.sub('\"', '', args)
			args = t
			if self._which('mkfs.%s' % type) != False:
				cmd = 'mkfs.%s -L %s %s %s' % (type, labl, re.sub("'", "", args), part)
		else:
			if self._which('mkswap') != False:
				cmd = 'mkswap -L %s %s' % (labl, part)
		sys.stdout.write('[ ] Formatting %s as %s\r' % (part,type))
		sys.stdout.flush()
		self._exec_cmd(cmd)
		sys.stdout.write('\r[+]\n')
		return

	def mount_partition(self, txt):
		line = self._chk_subs(txt).split()
		line.pop(0)
		cmd = 'mount '
		if len(line) > 3:
			who = line[0]
			line.pop(0)
			what = line[0]
			line.pop(0)
			where = line[0]
			line.pop(0)
			opts = ''
			for i in line:
				opts = opts+i+' '
			t = re.sub('\"','',opts)
			opts = t
			t = re.sub("'", '', opts)
			opts = t
			gen = 1
		elif len(line) == 3:
			who = line[0]
			what = line[1]
			where = line[2]
			gen = 1
		elif len(line) == 2:
			gen = 0
			if line[0] == 'proc':
				cmd = cmd+'-t proc proc %s' % line[1]
				if os.path.isdir(line[1]) == False:
					self._exec_cmd('mkdir %s && sleep 1' % line[1])
				who = 'proc'
				where = line[1]
		
		if gen == 1:
			if len(line) == 3:
				if what == 'auto':
					cmd = cmd+'%s %s' % (who, where)
				else:
					cmd = cmd+'-t %s %s %s' % (what, who, where)
			else:
				if what == 'auto':
					cmd = cmd+'-o %s %s %s' % (opts, who, where)
				else:
					if what != 'none':
						cmd = cmd+'-o %s -t %s %s %s' % (opts, what, who, where)
					else:
						cmd = cmd+'-o %s %s %s' % (opts, who, where)
			if os.path.isdir(where) == False:
				self._exec_cmd('mkdir %s && sleep 1' % where)
		sys.stdout.write('[ ] Mounting %s on %s' % (who, where))
		sys.stdout.flush()
		self._exec_cmd(cmd)
		sys.stdout.write('\r[+]')
		print ''
		return

	def swapon(self, txt):
		tmp = self._chk_subs(txt).split()
		tmp.pop(0)
		for i in tmp:
			if self._which('swapon') != False:
				cmd = 'swapon %s' % i
				sys.stdout.write('[ ] Activating swap on %s' % i)
				sys.stdout.flush()
				self._exec_cmd(cmd)
				sys.stdout.write('\r[+]\n')
		return

	def fetch(self, txt):
		tmp = self._chk_subs(txt)
		uri = tmp.split()[1]
		tmp = net.Fetch(uri)
		return

	def fetch_and_extract(self, txt):
		tmp = self._chk_subs(txt)
		uri = tmp.split()[1]
		archive = os.path.basename(uri)
		try: lcation = tmp.split()[2]
		except: lcation = './'
		if archive[0] == '%':
			archive_t = self._chk_subs(archive)
			archive = archive_t
		if lcation[0] == '%':
			lcation_t = self._chk_subs(lcation)
			lcation = lcation_t
		if archive[-2:] == 'z2': args = '-jxf'
		if archive[-2:] == 'gz': args = '-zxf'
		tmp = net.FandA(uri, lcation)
		return

	def exec_command(self, txt):
		ln_t = self._chk_subs(txt).split()
		ln_t.pop(0)
		li_t = ''
		for i in ln_t: li_t = li_t+i+' '
		if li_t[0].isalpha() == False and li_t[len(li_t)-1].isalpha() == False:
			line = li_t.strip()[1:][:-1]
		elif li_t[0].isalpha() == False and li_t[len(li_t)-1].isalpha() == True:
			line = li_t[1:]
		elif li_t[0].isalpha() == True and li_t[len(li_t)-1].isalpha() == False:
			line = li_t.strip()[:-1]
		else: line = li_t
		self._exec_cmd(line, flag=0)
		return

	def chroot_command(self, txt):
		tmp = self._chk_subs(txt)
		line = tmp.split()
		line.pop(0)
		script = ''
		for i in line: script = script+i+' '
		self.chroot_commands.append(script)
		return

	def chroot_batch(self, txt):
		tmp = self._chk_subs(txt)
		chroot = tmp.split()[1]
		sys.stdout.write('[ ] Executing commands in chroot.')
		sys.stdout.flush()
		fp = open('%s/chroot-commands.sh' % chroot, 'w+')
		fp.write('#!/bin/bash -x\n')
		for i in self.chroot_commands:
			line = i[1:][:-2]
			fp.write(line+'\n')
		self._exec_cmd('chmod +x %s/chroot-commands.sh' % chroot)
		fp.close()
		time.sleep(1)
		self._exec_cmd('chroot %s ./chroot-commands.sh' % chroot)
		sys.stdout.write('\r[+]\n')
		self.chroot_commands = []
		return

	def _exec_cmd(self, cmd, flag=1):
		line = self._chk_subs(cmd)
		if flag != 1: sys.stdout.write('[ ]  %s...' % line[:55])
		if flag != 1: self.cmd_log.write('\n## THUNDER: exec-command\n%s\n' % line)
		if self.DEBUG == True: self.watcher.logEvent('debug', 'Executing command: %s' % line)
		else: self.cmd_log.write('%s\n' % line)
		pipe = popen2.Popen4(line)
		buff = pipe.fromchild.readline()
		while buff != '':
			self.cmd_log.write(buff.strip()+'\n')
			buff = pipe.fromchild.readline()
		if pipe.poll() > 0:
			sys.stdout.write('\r[X] Error while running command:\n%s...\n' % line)
			sys.exit(255)
		else:
			if flag != 1: sys.stdout.write('\r[+] %s...\n' % line[:55])
		return

	def _chk_subs(self, txt):
		key = ''
		retv = ''
		for i in txt.split():
			if i[0] == '%':
				key = i[1:]	
				for a in self.th_vars:
					if key == a[0]:
						 retv = retv+a[1]+' '
			else:
				retv = retv+i+' '
		return retv
	
	def _which(self, prog):
		for path in os.getenv('PATH').split(':'):
			if os.path.isdir(path):
				for file in os.listdir(path):
					if file == prog:
						return os.path.join(path, file) 
		return False

	def _toggle_debug(self):
		if self.DEBUG == False: self.DEBUG = True
		if self.DEBUG == True: self.DEBUG = False
		return None


from __future__ import absolute_import
__copyright__ = "Copyright (C) 2013 David Braam - Released under terms of the AGPLv3 License"

import cStringIO as StringIO
import zipfile
import os
try:
	from xml.etree import cElementTree as ElementTree
except:
	from xml.etree import ElementTree

from Cura.util import mesh

def loadScene(filename):
	try:
		zfile = zipfile.ZipFile(filename)
		xml = zfile.read(zfile.namelist()[0])
		zfile.close()
	except zipfile.BadZipfile:
		f = open(filename, "r")
		xml = f.read()
		f.close()
	amf = ElementTree.fromstring(xml)
	if 'unit' in amf.attrib:
		unit = amf.attrib['unit'].lower()
	else:
		unit = 'millimeter'
	if unit == 'millimeter':
		scale = 1.0
	elif unit == 'meter':
		scale = 1000.0
	elif unit == 'inch':
		scale = 25.4
	elif unit == 'feet':
		scale = 304.8
	elif unit == 'micron':
		scale = 0.001
	else:
		print "Unknown unit in amf: %s" % (unit)
		scale = 1.0

	ret = []
	for amfObj in amf.iter('object'):
		obj = mesh.printableObject(os.path.basename(filename))
		for amfMesh in amfObj.iter('mesh'):
			vertexList = []
			for vertices in amfMesh.iter('vertices'):
				for vertex in vertices.iter('vertex'):
					for coordinates in vertex.iter('coordinates'):
						v = [0.0,0.0,0.0]
						for t in coordinates:
							if t.tag == 'x':
								v[0] = float(t.text)
							elif t.tag == 'y':
								v[1] = float(t.text)
							elif t.tag == 'z':
								v[2] = float(t.text)
						vertexList.append(v)

			for volume in amfMesh.iter('volume'):
				m = obj._addMesh()
				count = 0
				for triangle in volume.iter('triangle'):
					count += 1
				m._prepareFaceCount(count)

				for triangle in volume.iter('triangle'):
					for t in triangle:
						if t.tag == 'v1':
							v1 = vertexList[int(t.text)]
						elif t.tag == 'v2':
							v2 = vertexList[int(t.text)]
						elif t.tag == 'v3':
							v3 = vertexList[int(t.text)]
							m._addFace(v1[0], v1[1], v1[2], v2[0], v2[1], v2[2], v3[0], v3[1], v3[2])
		obj._postProcessAfterLoad()
		ret.append(obj)

	return ret

def saveScene(filename, objects):
	xml = StringIO.StringIO()
	xml.write('<?xml version="1.0" encoding="utf-8"?>\n')
	xml.write('<amf unit="millimeter" version="1.1">\n')
	n = 0
	for obj in objects:
		n += 1
		xml.write('  <object id="%d">\n' % (n))
		xml.write('    <mesh>\n')
		xml.write('      <vertices>\n')
		for m in obj._meshList:
			for v in m.getTransformedVertexes(True):
				xml.write('        <vertex>\n')
				xml.write('          <coordinates>\n')
				xml.write('            <x>%f</x>\n' % (v[0]))
				xml.write('            <y>%f</y>\n' % (v[1]))
				xml.write('            <z>%f</z>\n' % (v[2]))
				xml.write('          </coordinates>\n')
				xml.write('        </vertex>\n')
		xml.write('      </vertices>\n')

		idxOffset = 0
		for m in obj._meshList:
			xml.write('      <volume>\n')
			for idx in xrange(0, len(m.vertexes), 3):
				xml.write('        <triangle>\n')
				xml.write('          <v1>%i</v1>\n' % (idx + idxOffset))
				xml.write('          <v2>%i</v2>\n' % (idx + idxOffset + 1))
				xml.write('          <v3>%i</v3>\n' % (idx + idxOffset + 2))
				xml.write('        </triangle>\n')
			xml.write('      </volume>\n')
			xml.write('    </mesh>\n')
			idxOffset += len(m.vertexes)
		xml.write('  </object>\n')

	n += 1
	xml.write('  <constellation id="%d">\n' % (n))
	for idx in xrange(1, n):
		xml.write('    <instance objectid="%d">\n' % (idx))
		xml.write('      <deltax>0</deltax>\n')
		xml.write('      <deltay>0</deltay>\n')
		xml.write('      <deltaz>0</deltaz>\n')
		xml.write('      <rx>0</rx>\n')
		xml.write('      <ry>0</ry>\n')
		xml.write('      <rz>0</rz>\n')
		xml.write('    </instance>\n')
	xml.write('  </constellation>\n')
	xml.write('</amf>\n')

	zfile = zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED)
	zfile.writestr(filename, xml.getvalue())
	zfile.close()
	xml.close()

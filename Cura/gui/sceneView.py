from __future__ import absolute_import

import wx
import numpy
import time
import os
import traceback
import shutil

import OpenGL
OpenGL.ERROR_CHECKING = False
from OpenGL.GLU import *
from OpenGL.GL import *

from Cura.gui import printWindow
from Cura.util import profile
from Cura.util import meshLoader
from Cura.util import objectScene
from Cura.util import resources
from Cura.util import sliceEngine
from Cura.util import machineCom
from Cura.util import removableStorage
from Cura.gui.util import previewTools
from Cura.gui.util import opengl
from Cura.gui.util import openglGui

class SceneView(openglGui.glGuiPanel):
	def __init__(self, parent):
		super(SceneView, self).__init__(parent)

		self._yaw = 30
		self._pitch = 60
		self._zoom = 300
		self._scene = objectScene.Scene()
		self._objectShader = None
		self._focusObj = None
		self._selectedObj = None
		self._objColors = [None,None,None,None]
		self._mouseX = -1
		self._mouseY = -1
		self._mouseState = None
		self._viewTarget = numpy.array([0,0,0], numpy.float32)
		self._animView = None
		self._animZoom = None
		self._platformMesh = meshLoader.loadMeshes(resources.getPathForMesh('ultimaker_platform.stl'))[0]
		self._platformMesh._drawOffset = numpy.array([0,0,1.5], numpy.float32)
		self._isSimpleMode = True

		self._viewport = None
		self._modelMatrix = None
		self._projMatrix = None
		self.tempMatrix = None

		self.openFileButton      = openglGui.glButton(self, 4, 'Load', (0,0), self.ShowLoadModel)
		self.printButton         = openglGui.glButton(self, 6, 'Print', (1,0), self.ShowPrintWindow)
		self.printButton.setDisabled(True)

		group = []
		self.rotateToolButton = openglGui.glRadioButton(self, 8, 'Rotate', (0,-1), group, self.OnToolSelect)
		self.scaleToolButton  = openglGui.glRadioButton(self, 9, 'Scale', (1,-1), group, self.OnToolSelect)
		self.mirrorToolButton  = openglGui.glRadioButton(self, 10, 'Mirror', (2,-1), group, self.OnToolSelect)

		self.resetRotationButton = openglGui.glButton(self, 12, 'Reset', (0,-2), self.OnRotateReset)
		self.layFlatButton       = openglGui.glButton(self, 16, 'Lay flat', (0,-3), self.OnLayFlat)

		self.resetScaleButton    = openglGui.glButton(self, 13, 'Reset', (1,-2), self.OnScaleReset)
		self.scaleMaxButton      = openglGui.glButton(self, 17, 'To max', (1,-3), self.OnScaleMax)

		self.mirrorXButton       = openglGui.glButton(self, 14, 'Mirror X', (2,-2), lambda button: self.OnMirror(0))
		self.mirrorYButton       = openglGui.glButton(self, 18, 'Mirror Y', (2,-3), lambda button: self.OnMirror(1))
		self.mirrorZButton       = openglGui.glButton(self, 22, 'Mirror Z', (2,-4), lambda button: self.OnMirror(2))

		self.rotateToolButton.setExpandArrow(True)
		self.scaleToolButton.setExpandArrow(True)
		self.mirrorToolButton.setExpandArrow(True)

		self.scaleForm = openglGui.glFrame(self, (2, -2))
		openglGui.glGuiLayoutGrid(self.scaleForm)
		openglGui.glLabel(self.scaleForm, 'Scale X', (0,0))
		self.scaleXctrl = openglGui.glNumberCtrl(self.scaleForm, '1.0', (1,0), lambda value: self.OnScaleEntry(value, 0))
		openglGui.glLabel(self.scaleForm, 'Scale Y', (0,1))
		self.scaleYctrl = openglGui.glNumberCtrl(self.scaleForm, '1.0', (1,1), lambda value: self.OnScaleEntry(value, 1))
		openglGui.glLabel(self.scaleForm, 'Scale Z', (0,2))
		self.scaleZctrl = openglGui.glNumberCtrl(self.scaleForm, '1.0', (1,2), lambda value: self.OnScaleEntry(value, 2))
		openglGui.glLabel(self.scaleForm, 'Size X (mm)', (0,4))
		self.scaleXmmctrl = openglGui.glNumberCtrl(self.scaleForm, '0.0', (1,4), lambda value: self.OnScaleEntryMM(value, 0))
		openglGui.glLabel(self.scaleForm, 'Size Y (mm)', (0,5))
		self.scaleYmmctrl = openglGui.glNumberCtrl(self.scaleForm, '0.0', (1,5), lambda value: self.OnScaleEntryMM(value, 1))
		openglGui.glLabel(self.scaleForm, 'Size Z (mm)', (0,6))
		self.scaleZmmctrl = openglGui.glNumberCtrl(self.scaleForm, '0.0', (1,6), lambda value: self.OnScaleEntryMM(value, 2))
		openglGui.glLabel(self.scaleForm, 'Uniform scale', (0,8))
		self.scaleUniform = openglGui.glCheckbox(self.scaleForm, True, (1,8), None)

		self.notification = openglGui.glNotification(self, (0, 0))

		self._slicer = sliceEngine.Slicer(self._updateSliceProgress)
		self._sceneUpdateTimer = wx.Timer(self)
		self.Bind(wx.EVT_TIMER, lambda e : self._slicer.runSlicer(self._scene), self._sceneUpdateTimer)
		self.Bind(wx.EVT_MOUSEWHEEL, self.OnMouseWheel)

		self.OnToolSelect(0)
		self.updateToolButtons()
		self.updateProfileToControls()

	def ShowLoadModel(self, button):
		if button == 1:
			dlg=wx.FileDialog(self, 'Open 3D model', os.path.split(profile.getPreference('lastFile'))[0], style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST)
			dlg.SetWildcard(meshLoader.wildcardFilter())
			if dlg.ShowModal() != wx.ID_OK:
				dlg.Destroy()
				return
			filename = dlg.GetPath()
			dlg.Destroy()
			if not(os.path.exists(filename)):
				return False
			profile.putPreference('lastFile', filename)
			self.GetParent().GetParent().GetParent().addToModelMRU(filename)
			self.loadScene([filename])

	def ShowPrintWindow(self, button):
		if button == 1:
			if machineCom.machineIsConnected():
				printWindow.printFile(self._slicer.getGCodeFilename())
			elif len(removableStorage.getPossibleSDcardDrives()) > 0:
				drives = removableStorage.getPossibleSDcardDrives()
				if len(drives) > 1:
					drive = drives[0]
				else:
					drive = drives[0]
				filename = os.path.basename(profile.getPreference('lastFile'))
				filename = filename[0:filename.rfind('.')] + '.gcode'
				shutil.copy(self._slicer.getGCodeFilename(), drive[1] + filename)
				self.notification.message("Saved as %s" % (drive[1] + filename))
			else:
				defPath = profile.getPreference('lastFile')
				defPath = defPath[0:defPath.rfind('.')] + '.gcode'
				dlg=wx.FileDialog(self, 'Save toolpath', defPath, style=wx.FD_SAVE)
				dlg.SetFilename(defPath)
				dlg.SetWildcard('Toolpath (*.gcode)|*.gcode;*.g')
				if dlg.ShowModal() != wx.ID_OK:
					dlg.Destroy()
					return
				filename = dlg.GetPath()
				dlg.Destroy()

				shutil.copy(self._slicer.getGCodeFilename(), filename)
				self.notification.message("Saved as %s" % (filename))

	def OnToolSelect(self, button):
		if self.rotateToolButton.getSelected():
			self.tool = previewTools.toolRotate(self)
		elif self.scaleToolButton.getSelected():
			self.tool = previewTools.toolScale(self)
		elif self.mirrorToolButton.getSelected():
			self.tool = previewTools.toolNone(self)
		else:
			self.tool = previewTools.toolNone(self)
		self.resetRotationButton.setHidden(not self.rotateToolButton.getSelected())
		self.layFlatButton.setHidden(not self.rotateToolButton.getSelected())
		self.resetScaleButton.setHidden(not self.scaleToolButton.getSelected())
		self.scaleMaxButton.setHidden(not self.scaleToolButton.getSelected())
		self.scaleForm.setHidden(not self.scaleToolButton.getSelected())
		self.mirrorXButton.setHidden(not self.mirrorToolButton.getSelected())
		self.mirrorYButton.setHidden(not self.mirrorToolButton.getSelected())
		self.mirrorZButton.setHidden(not self.mirrorToolButton.getSelected())

	def updateToolButtons(self):
		if self._selectedObj is None:
			hidden = True
		else:
			hidden = False
		self.rotateToolButton.setHidden(hidden)
		self.scaleToolButton.setHidden(hidden)
		self.mirrorToolButton.setHidden(hidden)
		if hidden:
			self.rotateToolButton.setSelected(False)
			self.scaleToolButton.setSelected(False)
			self.mirrorToolButton.setSelected(False)
			self.OnToolSelect(0)

	def OnRotateReset(self, button):
		if self._selectedObj is None:
			return
		self._selectedObj.resetRotation()

	def OnLayFlat(self, button):
		if self._selectedObj is None:
			return
		self._selectedObj.layFlat()

	def OnScaleReset(self, button):
		if self._selectedObj is None:
			return
		self._selectedObj.resetScale()

	def OnScaleMax(self, button):
		if self._selectedObj is None:
			return
		self._selectedObj.scaleUpTo(self._machineSize - numpy.array(profile.calculateObjectSizeOffsets() + [0.0], numpy.float32) * 2)

	def OnMirror(self, axis):
		if self._selectedObj is None:
			return
		self._selectedObj.mirror(axis)
		self.sceneUpdated()

	def OnScaleEntry(self, value, axis):
		if self._selectedObj is None:
			return
		try:
			value = float(value)
		except:
			return
		self._selectedObj.setScale(value, axis, self.scaleUniform.getValue())
		self.updateProfileToControls()
		self.sceneUpdated()

	def OnScaleEntryMM(self, value, axis):
		if self._selectedObj is None:
			return
		try:
			value = float(value)
		except:
			return
		self._selectedObj.setSize(value, axis, self.scaleUniform.getValue())
		self.updateProfileToControls()
		self.sceneUpdated()

	def OnDuplicateObject(self, e):
		if self._selectedObj is None:
			return
		self._scene.add(self._selectedObj.copy())
		self._scene.centerAll()
		self.sceneUpdated()

	def OnSplitObject(self, e):
		if self._selectedObj is None:
			return
		self._scene.remove(self._selectedObj)
		for obj in self._selectedObj.split():
			self._scene.add(obj)
		self._scene.centerAll()
		self._selectObject(None)
		self.sceneUpdated()

	def OnMergeObjects(self, e):
		if self._selectedObj is None or self._focusObj is None or self._selectedObj == self._focusObj:
			return
		self._scene.merge(self._selectedObj, self._focusObj)
		self.sceneUpdated()

	def sceneUpdated(self):
		self._sceneUpdateTimer.Start(1, True)
		self._slicer.abortSlicer()
		self._scene.setSizeOffsets(numpy.array(profile.calculateObjectSizeOffsets(), numpy.float32))
		self.Refresh()

	def _updateSliceProgress(self, progressValue, ready):
		self.printButton.setDisabled(not ready)
		self.printButton.setProgressBar(progressValue)
		self.Refresh()

	def loadScene(self, fileList):
		for filename in fileList:
			try:
				objList = meshLoader.loadMeshes(filename)
			except:
				traceback.print_exc()
			else:
				for obj in objList:
					obj._loadAnim = openglGui.animation(self, 1, 0, 1.5)
					self._scene.add(obj)
					self._scene.centerAll()
					self._selectObject(obj)
		self.sceneUpdated()

	def _deleteObject(self, obj):
		if obj == self._selectedObj:
			self._selectObject(None)
		if obj == self._focusObj:
			self._focusObj = None
		self._scene.remove(obj)
		for m in obj._meshList:
			if m.vbo is not None and m.vbo.decRef():
				self.glReleaseList.append(m.vbo)
		if self._isSimpleMode:
			self._scene.arrangeAll()
		self.sceneUpdated()

	def _selectObject(self, obj, zoom = True):
		if obj != self._selectedObj:
			self._selectedObj = obj
			self.updateProfileToControls()
			self.updateToolButtons()
		if zoom and obj is not None:
			newViewPos = numpy.array([obj.getPosition()[0], obj.getPosition()[1], obj.getMaximum()[2] / 2])
			self._animView = openglGui.animation(self, self._viewTarget.copy(), newViewPos, 0.5)
			newZoom = obj.getBoundaryCircle() * 6
			if newZoom > numpy.max(self._machineSize) * 3:
				newZoom = numpy.max(self._machineSize) * 3
			self._animZoom = openglGui.animation(self, self._zoom, newZoom, 0.5)

	def updateProfileToControls(self):
		oldSimpleMode = self._isSimpleMode
		self._isSimpleMode = profile.getPreference('startMode') == 'Simple'
		if self._isSimpleMode and not oldSimpleMode:
			self._scene.arrangeAll()
			self.sceneUpdated()
		self._machineSize = numpy.array([profile.getPreferenceFloat('machine_width'), profile.getPreferenceFloat('machine_depth'), profile.getPreferenceFloat('machine_height')])
		self._objColors[0] = profile.getPreferenceColour('model_colour')
		self._objColors[1] = profile.getPreferenceColour('model_colour2')
		self._objColors[2] = profile.getPreferenceColour('model_colour3')
		self._objColors[3] = profile.getPreferenceColour('model_colour4')
		self._scene.setMachineSize(self._machineSize)
		self._scene.setSizeOffsets(numpy.array(profile.calculateObjectSizeOffsets(), numpy.float32))
		self._scene.setHeadSize(profile.getPreferenceFloat('extruder_head_size_min_x'), profile.getPreferenceFloat('extruder_head_size_max_x'), profile.getPreferenceFloat('extruder_head_size_min_y'), profile.getPreferenceFloat('extruder_head_size_max_y'), profile.getPreferenceFloat('extruder_head_size_height'))

		if self._selectedObj is not None:
			scale = self._selectedObj.getScale()
			size = self._selectedObj.getSize()
			self.scaleXctrl.setValue(round(scale[0], 2))
			self.scaleYctrl.setValue(round(scale[1], 2))
			self.scaleZctrl.setValue(round(scale[2], 2))
			self.scaleXmmctrl.setValue(round(size[0], 2))
			self.scaleYmmctrl.setValue(round(size[1], 2))
			self.scaleZmmctrl.setValue(round(size[2], 2))

	def OnKeyChar(self, keyCode):
		if keyCode == wx.WXK_DELETE or keyCode == wx.WXK_NUMPAD_DELETE:
			if self._selectedObj is not None:
				self._deleteObject(self._selectedObj)
				self.Refresh()

		if keyCode == wx.WXK_F3 and wx.GetKeyState(wx.WXK_SHIFT):
			shaderEditor(self, self.ShaderUpdate, self._objectLoadShader.getVertexShader(), self._objectLoadShader.getFragmentShader())

	def ShaderUpdate(self, v, f):
		s = opengl.GLShader(v, f)
		if s.isValid():
			self._objectLoadShader.release()
			self._objectLoadShader = s
			for obj in self._scene.objects():
				obj._loadAnim = openglGui.animation(self, 1, 0, 1.5)
			self.Refresh()

	def OnMouseDown(self,e):
		self._mouseX = e.GetX()
		self._mouseY = e.GetY()
		self._mouseClick3DPos = self._mouse3Dpos
		self._mouseClickFocus = self._focusObj
		if e.ButtonDClick():
			self._mouseState = 'doubleClick'
		else:
			self._mouseState = 'dragOrClick'
		p0, p1 = self.getMouseRay(self._mouseX, self._mouseY)
		p0 -= self.getObjectCenterPos() - self._viewTarget
		p1 -= self.getObjectCenterPos() - self._viewTarget
		if self.tool.OnDragStart(p0, p1):
			self._mouseState = 'tool'
		if self._mouseState == 'dragOrClick':
			if e.GetButton() == 1:
				if self._focusObj is not None:
					self._selectObject(self._focusObj, False)
					self.Refresh()

	def OnMouseUp(self, e):
		if e.LeftIsDown() or e.MiddleIsDown() or e.RightIsDown():
			return
		if self._mouseState == 'dragOrClick':
			if e.GetButton() == 1:
				self._selectObject(self._focusObj)
			if e.GetButton() == 3:
				if self._selectedObj is not None:
					menu = wx.Menu()
					self.Bind(wx.EVT_MENU, lambda e: self._deleteObject(self._selectedObj), menu.Append(-1, 'Delete'))
					if self._selectedObj == self._focusObj:
						self.Bind(wx.EVT_MENU, self.OnDuplicateObject, menu.Append(-1, 'Duplicate'))
						self.Bind(wx.EVT_MENU, self.OnSplitObject, menu.Append(-1, 'Split'))
					if self._selectedObj != self._focusObj and self._focusObj is not None:
						self.Bind(wx.EVT_MENU, self.OnMergeObjects, menu.Append(-1, 'Dual extrusion merge'))
					if menu.MenuItemCount > 0:
						self.PopupMenu(menu)
					menu.Destroy()
		elif self._mouseState == 'dragObject' and self._selectedObj is not None:
			self._scene.pushFree()
			self.sceneUpdated()
		elif self._mouseState == 'tool':
			if self.tempMatrix is not None and self._selectedObj is not None:
				self._selectedObj.applyMatrix(self.tempMatrix)
			self.tempMatrix = None
			self.tool.OnDragEnd()
			self.sceneUpdated()
		self._mouseState = None

	def OnMouseMotion(self,e):
		p0, p1 = self.getMouseRay(e.GetX(), e.GetY())
		p0 -= self.getObjectCenterPos() - self._viewTarget
		p1 -= self.getObjectCenterPos() - self._viewTarget

		if e.Dragging() and self._mouseState is not None:
			if self._mouseState == 'tool':
				self.tool.OnDrag(p0, p1)
			elif not e.LeftIsDown() and e.RightIsDown():
				self._mouseState = 'drag'
				self._yaw += e.GetX() - self._mouseX
				self._pitch -= e.GetY() - self._mouseY
				if self._pitch > 170:
					self._pitch = 170
				if self._pitch < 10:
					self._pitch = 10
			elif (e.LeftIsDown() and e.RightIsDown()) or e.MiddleIsDown():
				self._mouseState = 'drag'
				self._zoom += e.GetY() - self._mouseY
				if self._zoom < 1:
					self._zoom = 1
				if self._zoom > numpy.max(self._machineSize) * 3:
					self._zoom = numpy.max(self._machineSize) * 3
			elif e.LeftIsDown() and self._selectedObj is not None and self._selectedObj == self._mouseClickFocus and not self._isSimpleMode:
				self._mouseState = 'dragObject'
				z = max(0, self._mouseClick3DPos[2])
				p0, p1 = self.getMouseRay(self._mouseX, self._mouseY)
				p2, p3 = self.getMouseRay(e.GetX(), e.GetY())
				p0[2] -= z
				p1[2] -= z
				p2[2] -= z
				p3[2] -= z
				cursorZ0 = p0 - (p1 - p0) * (p0[2] / (p1[2] - p0[2]))
				cursorZ1 = p2 - (p3 - p2) * (p2[2] / (p3[2] - p2[2]))
				diff = cursorZ1 - cursorZ0
				self._selectedObj.setPosition(self._selectedObj.getPosition() + diff[0:2])
		if not e.Dragging() or self._mouseState != 'tool':
			self.tool.OnMouseMove(p0, p1)

		self._mouseX = e.GetX()
		self._mouseY = e.GetY()

	def OnMouseWheel(self, e):
		self._zoom *= 1.0 - float(e.GetWheelRotation() / e.GetWheelDelta()) / 10.0
		if self._zoom < 1.0:
			self._zoom = 1.0
		if self._zoom > numpy.max(self._machineSize) * 3:
			self._zoom = numpy.max(self._machineSize) * 3
		self.Refresh()

	def getMouseRay(self, x, y):
		if self._viewport is None:
			return numpy.array([0,0,0],numpy.float32), numpy.array([0,0,1],numpy.float32)
		p0 = opengl.unproject(x, self._viewport[1] + self._viewport[3] - y, 0, self._modelMatrix, self._projMatrix, self._viewport)
		p1 = opengl.unproject(x, self._viewport[1] + self._viewport[3] - y, 1, self._modelMatrix, self._projMatrix, self._viewport)
		p0 -= self._viewTarget
		p1 -= self._viewTarget
		return p0, p1

	def _init3DView(self):
		# set viewing projection
		size = self.GetSize()
		glViewport(0, 0, size.GetWidth(), size.GetHeight())
		glLoadIdentity()

		glLightfv(GL_LIGHT0, GL_POSITION, [0.2, 0.2, 1.0, 0.0])

		glDisable(GL_RESCALE_NORMAL)
		glDisable(GL_LIGHTING)
		glDisable(GL_LIGHT0)
		glEnable(GL_DEPTH_TEST)
		glDisable(GL_CULL_FACE)
		glDisable(GL_BLEND)
		glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

		glClearColor(0.8, 0.8, 0.8, 1.0)
		glClearStencil(0)
		glClearDepth(1.0)

		glMatrixMode(GL_PROJECTION)
		glLoadIdentity()
		aspect = float(size.GetWidth()) / float(size.GetHeight())
		gluPerspective(45.0, aspect, 1.0, numpy.max(self._machineSize) * 4)

		glMatrixMode(GL_MODELVIEW)
		glLoadIdentity()
		glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)

	def OnPaint(self,e):
		if machineCom.machineIsConnected():
			self.printButton._imageID = 6
			self.printButton._tooltip = 'Print'
		elif len(removableStorage.getPossibleSDcardDrives()) > 0:
			self.printButton._imageID = 2
			self.printButton._tooltip = 'Toolpath to SD'
		else:
			self.printButton._imageID = 3
			self.printButton._tooltip = 'Save toolpath'

		if self._animView is not None:
			self._viewTarget = self._animView.getPosition()
			if self._animView.isDone():
				self._animView = None
		if self._animZoom is not None:
			self._zoom = self._animZoom.getPosition()
			if self._animZoom.isDone():
				self._animZoom = None
		if self._objectShader is None:
			self._objectShader = opengl.GLShader("""
varying float light_amount;

void main(void)
{
    gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
    gl_FrontColor = gl_Color;

	light_amount = abs(dot(normalize(gl_NormalMatrix * gl_Normal), normalize(gl_LightSource[0].position.xyz)));
	light_amount += 0.2;
}
			""","""
varying float light_amount;

void main(void)
{
	gl_FragColor = vec4(gl_Color.xyz * light_amount, gl_Color[3]);
}
			""")
			self._objectLoadShader = opengl.GLShader("""
uniform float intensity;
uniform float scale;
varying float light_amount;

void main(void)
{
	vec4 tmp = gl_Vertex;
    tmp.x += sin(tmp.z/5.0+intensity*30.0) * scale * intensity;
    tmp.y += sin(tmp.z/3.0+intensity*40.0) * scale * intensity;
    gl_Position = gl_ModelViewProjectionMatrix * tmp;
    gl_FrontColor = gl_Color;

	light_amount = abs(dot(normalize(gl_NormalMatrix * gl_Normal), normalize(gl_LightSource[0].position.xyz)));
	light_amount += 0.2;
}
			""","""
uniform float intensity;
varying float light_amount;

void main(void)
{
	gl_FragColor = vec4(gl_Color.xyz * light_amount, 1.0-intensity);
}
			""")
		self._init3DView()
		glTranslate(0,0,-self._zoom)
		glRotate(-self._pitch, 1,0,0)
		glRotate(self._yaw, 0,0,1)
		glTranslate(-self._viewTarget[0],-self._viewTarget[1],-self._viewTarget[2])

		self._viewport = glGetIntegerv(GL_VIEWPORT)
		self._modelMatrix = glGetDoublev(GL_MODELVIEW_MATRIX)
		self._projMatrix = glGetDoublev(GL_PROJECTION_MATRIX)

		glClearColor(1,1,1,1)
		glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)

		for n in xrange(0, len(self._scene.objects())):
			obj = self._scene.objects()[n]
			glColor4ub((n >> 24) & 0xFF, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF)
			self._renderObject(obj)

		if self._mouseX > -1:
			n = glReadPixels(self._mouseX, self.GetSize().GetHeight() - 1 - self._mouseY, 1, 1, GL_RGBA, GL_UNSIGNED_INT_8_8_8_8)[0][0]
			if n < len(self._scene.objects()):
				self._focusObj = self._scene.objects()[n]
			else:
				self._focusObj = None
			f = glReadPixels(self._mouseX, self.GetSize().GetHeight() - 1 - self._mouseY, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT)[0][0]
			self._mouse3Dpos = opengl.unproject(self._mouseX, self._viewport[1] + self._viewport[3] - self._mouseY, f, self._modelMatrix, self._projMatrix, self._viewport)
			self._mouse3Dpos -= self._viewTarget

		self._init3DView()
		glTranslate(0,0,-self._zoom)
		glRotate(-self._pitch, 1,0,0)
		glRotate(self._yaw, 0,0,1)
		glTranslate(-self._viewTarget[0],-self._viewTarget[1],-self._viewTarget[2])

		glStencilFunc(GL_ALWAYS, 1, 1)
		glStencilOp(GL_INCR, GL_INCR, GL_INCR)
		self._objectShader.bind()
		for obj in self._scene.objects():
			if obj._loadAnim is not None:
				if obj._loadAnim.isDone():
					obj._loadAnim = None
				else:
					continue
			brightness = 1.0
			glDisable(GL_STENCIL_TEST)
			if self._selectedObj == obj:
				glEnable(GL_STENCIL_TEST)
			if self._focusObj == obj:
				brightness = 1.2
			elif self._focusObj is not None or self._selectedObj is not None and obj != self._selectedObj:
				brightness = 0.8
			if not self._scene.checkPlatform(obj):
				glColor4f(0.5 * brightness, 0.5 * brightness, 0.5 * brightness, 0.8 * brightness)
				self._renderObject(obj)
			else:
				self._renderObject(obj, brightness)
		self._objectShader.unbind()

		glDisable(GL_STENCIL_TEST)
		glEnable(GL_BLEND)
		self._objectLoadShader.bind()
		glColor4f(0.2, 0.6, 1.0, 1.0)
		for obj in self._scene.objects():
			if obj._loadAnim is None:
				continue
			self._objectLoadShader.setUniform('intensity', obj._loadAnim.getPosition())
			self._objectLoadShader.setUniform('scale', obj.getBoundaryCircle() / 10)
			self._renderObject(obj)
		self._objectLoadShader.unbind()
		glDisable(GL_BLEND)

		self._drawMachine()

		#Draw the object box-shadow, so you can see where it will collide with other objects.
		if self._selectedObj is not None and len(self._scene.objects()) > 1:
			size = self._selectedObj.getSize()[0:2] / 2 + self._scene.getObjectExtend()
			glPushMatrix()
			glTranslatef(self._selectedObj.getPosition()[0], self._selectedObj.getPosition()[1], 0.0)
			glEnable(GL_BLEND)
			glEnable(GL_CULL_FACE)
			glColor4f(0,0,0,0.12)
			glBegin(GL_QUADS)
			glVertex3f(-size[0],  size[1], 0.1)
			glVertex3f(-size[0], -size[1], 0.1)
			glVertex3f( size[0], -size[1], 0.1)
			glVertex3f( size[0],  size[1], 0.1)
			glEnd()
			glDisable(GL_CULL_FACE)
			glPopMatrix()

		#Draw the outline of the selected object, on top of everything else except the GUI.
		if self._selectedObj is not None and self._selectedObj._loadAnim is None:
			glDisable(GL_DEPTH_TEST)
			glEnable(GL_CULL_FACE)
			glEnable(GL_STENCIL_TEST)
			glDisable(GL_BLEND)
			glStencilFunc(GL_EQUAL, 0, 255)

			glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
			glLineWidth(2)
			glColor4f(1,1,1,0.5)
			self._renderObject(self._selectedObj)
			glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

			glViewport(0, 0, self.GetSize().GetWidth(), self.GetSize().GetHeight())
			glDisable(GL_STENCIL_TEST)
			glDisable(GL_CULL_FACE)
			glEnable(GL_DEPTH_TEST)

		if self._selectedObj is not None:
			glPushMatrix()
			pos = self.getObjectCenterPos()
			glTranslate(pos[0], pos[1], pos[2])
			self.tool.OnDraw()
			glPopMatrix()

	def _renderObject(self, obj, brightness = False):
		glPushMatrix()
		glTranslate(obj.getPosition()[0], obj.getPosition()[1], obj.getSize()[2] / 2)

		if self.tempMatrix is not None and obj == self._selectedObj:
			tempMatrix = opengl.convert3x3MatrixTo4x4(self.tempMatrix)
			glMultMatrixf(tempMatrix)

		offset = obj.getDrawOffset()
		glTranslate(-offset[0], -offset[1], -offset[2] - obj.getSize()[2] / 2)

		tempMatrix = opengl.convert3x3MatrixTo4x4(obj.getMatrix())
		glMultMatrixf(tempMatrix)

		n = 0
		for m in obj._meshList:
			if m.vbo is None:
				m.vbo = opengl.GLVBO(m.vertexes, m.normal)
			if brightness:
				glColor4fv(map(lambda n: n * brightness, self._objColors[n]))
				n += 1
			m.vbo.render()
		glPopMatrix()

	def _drawMachine(self):
		glEnable(GL_CULL_FACE)
		glEnable(GL_BLEND)

		if profile.getPreference('machine_type') == 'ultimaker':
			glColor4f(1,1,1,0.5)
			self._objectShader.bind()
			self._renderObject(self._platformMesh)
			self._objectShader.unbind()

		size = [profile.getPreferenceFloat('machine_width'), profile.getPreferenceFloat('machine_depth'), profile.getPreferenceFloat('machine_height')]
		v0 = [ size[0] / 2, size[1] / 2, size[2]]
		v1 = [ size[0] / 2,-size[1] / 2, size[2]]
		v2 = [-size[0] / 2, size[1] / 2, size[2]]
		v3 = [-size[0] / 2,-size[1] / 2, size[2]]
		v4 = [ size[0] / 2, size[1] / 2, 0]
		v5 = [ size[0] / 2,-size[1] / 2, 0]
		v6 = [-size[0] / 2, size[1] / 2, 0]
		v7 = [-size[0] / 2,-size[1] / 2, 0]

		vList = [v0,v1,v3,v2, v1,v0,v4,v5, v2,v3,v7,v6, v0,v2,v6,v4, v3,v1,v5,v7]
		glEnableClientState(GL_VERTEX_ARRAY)
		glVertexPointer(3, GL_FLOAT, 3*4, vList)

		glColor4ub(5, 171, 231, 64)
		glDrawArrays(GL_QUADS, 0, 4)
		glColor4ub(5, 171, 231, 96)
		glDrawArrays(GL_QUADS, 4, 8)
		glColor4ub(5, 171, 231, 128)
		glDrawArrays(GL_QUADS, 12, 8)

		sx = self._machineSize[0]
		sy = self._machineSize[1]
		for x in xrange(-int(sx/20)-1, int(sx / 20) + 1):
			for y in xrange(-int(sx/20)-1, int(sy / 20) + 1):
				x1 = x * 10
				x2 = x1 + 10
				y1 = y * 10
				y2 = y1 + 10
				x1 = max(min(x1, sx/2), -sx/2)
				y1 = max(min(y1, sy/2), -sy/2)
				x2 = max(min(x2, sx/2), -sx/2)
				y2 = max(min(y2, sy/2), -sy/2)
				if (x & 1) == (y & 1):
					glColor4ub(5, 171, 231, 127)
				else:
					glColor4ub(5 * 8 / 10, 171 * 8 / 10, 231 * 8 / 10, 128)
				glBegin(GL_QUADS)
				glVertex3f(x1, y1, -0.02)
				glVertex3f(x2, y1, -0.02)
				glVertex3f(x2, y2, -0.02)
				glVertex3f(x1, y2, -0.02)
				glEnd()

		glDisableClientState(GL_VERTEX_ARRAY)
		glDisable(GL_BLEND)
		glDisable(GL_CULL_FACE)

	def getObjectCenterPos(self):
		if self._selectedObj is None:
			return [0.0, 0.0, 0.0]
		pos = self._selectedObj.getPosition()
		size = self._selectedObj.getSize()
		return [pos[0], pos[1], size[2]/2]

	def getObjectBoundaryCircle(self):
		if self._selectedObj is None:
			return 0.0
		return self._selectedObj.getBoundaryCircle()

	def getObjectSize(self):
		if self._selectedObj is None:
			return [0.0, 0.0, 0.0]
		return self._selectedObj.getSize()

	def getObjectMatrix(self):
		if self._selectedObj is None:
			return numpy.matrix([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
		return self._selectedObj.getMatrix()

class shaderEditor(wx.Dialog):
	def __init__(self, parent, callback, v, f):
		super(shaderEditor, self).__init__(parent, title="Shader editor", style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
		self._callback = callback
		s = wx.BoxSizer(wx.VERTICAL)
		self.SetSizer(s)
		self._vertex = wx.TextCtrl(self, -1, v, style=wx.TE_MULTILINE)
		self._fragment = wx.TextCtrl(self, -1, f, style=wx.TE_MULTILINE)
		s.Add(self._vertex, 1, flag=wx.EXPAND)
		s.Add(self._fragment, 1, flag=wx.EXPAND)

		self._vertex.Bind(wx.EVT_TEXT, self.OnText, self._vertex)
		self._fragment.Bind(wx.EVT_TEXT, self.OnText, self._fragment)

		self.SetPosition(self.GetParent().GetPosition())
		self.SetSize((self.GetSize().GetWidth(), self.GetParent().GetSize().GetHeight()))
		self.Show()

	def OnText(self, e):
		self._callback(self._vertex.GetValue(), self._fragment.GetValue())
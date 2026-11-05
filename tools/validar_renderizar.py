"""Executar com blender --background --python tools/validar_renderizar.py."""
import json
import math
from pathlib import Path
import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'modelo'
dims = json.loads((OUT/'dimensoes.json').read_text())
pts = json.loads((OUT/'contornos.json').read_text())
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 0.001
scene.unit_settings.length_unit = 'MILLIMETERS'

reports = {}
main = None
for filename in ['lente.stl', 'lente_espelhada.stl']:
    bpy.ops.wm.stl_import(filepath=str(OUT/filename))
    obj = bpy.context.object
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.00001)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    edges_bad = sum(not edge.is_manifold for edge in bm.edges)
    degenerate = sum(face.calc_area() < 1e-10 for face in bm.faces)
    volume = bm.calc_volume(signed=True)
    euler = len(bm.verts)-len(bm.edges)+len(bm.faces)
    unseen = set(bm.verts)
    components = 0
    while unseen:
        components += 1
        queue = [unseen.pop()]
        while queue:
            current = queue.pop()
            for edge in current.link_edges:
                other = edge.other_vert(current)
                if other in unseen:
                    unseen.remove(other)
                    queue.append(other)
    tree = BVHTree.FromBMesh(bm, epsilon=0.000001)
    vertex_sets = [set(face.verts) for face in bm.faces]
    intersections = [(a,b) for a,b in tree.overlap(tree) if a < b and vertex_sets[a].isdisjoint(vertex_sets[b])]
    # Ponto central localizado dentro da abertura da referência.
    aperture_empty = tree.ray_cast(Vector((0,0,20)), Vector((0,0,-1)))[0] is None
    # Usa o ponto médio da faixa lateral externa/interna, na base.
    i = 50
    x,y = [(pts['externo'][i][k]+pts['interno'][i][k])*dims[key]/2
           for k,key in enumerate(('largura_mm','altura_mm'))]
    if 'espelhada' in filename:
        x = -x
    border_present = tree.ray_cast(Vector((x,y,20)), Vector((0,0,-1)))[0] is not None
    # Mede a flecha no verso, em X=0, no meio da faixa superior.
    def upper_crossing(points):
        hits = []
        for i,a in enumerate(points):
            b = points[(i+1)%len(points)]
            if (a[0] <= 0 < b[0]) or (b[0] <= 0 < a[0]):
                hits.append(a[1]+(b[1]-a[1])*(-a[0])/(b[0]-a[0]))
        return max(hits)*dims['altura_mm']
    yc = (upper_crossing(pts['externo'])+upper_crossing(pts['interno']))/2
    underside = tree.ray_cast(Vector((0,yc,-20)), Vector((0,0,1)))[0]
    front = tree.ray_cast(Vector((0,yc,30)), Vector((0,0,-1)))[0]
    # As extremidades em X pertencem ao mesmo plano traseiro Z=0.
    endpoints = [v.co.z for v in bm.verts if abs(abs(v.co.x)-dims['largura_mm']/2) < 0.0001]
    chord_plane = min(endpoints)
    measured_sagitta = underside.z-chord_plane if underside is not None else None
    measured_thickness = front.z-underside.z if underside is not None and front is not None else None
    expected_dimensions = [dims['largura_mm'],dims['altura_mm'],dims['profundidade_total_mm']]
    dimensions_ok = all(abs(a-b) < 0.001 for a,b in zip(obj.dimensions,expected_dimensions))
    curvature_ok = measured_sagitta is not None and abs(measured_sagitta-dims['flecha_mm']) < 0.01
    # A espessura agora varia com o perfil abaulado; mede-se a crista máxima.
    r = dims['raio_curvatura_mm']
    def base_z(x):
        return math.sqrt(max(0,r*r-x*x))-(r-dims['flecha_mm']) if r else 0
    max_thickness = max(v.co.z-base_z(v.co.x) for v in bm.verts)
    min_thickness = min(v.co.z-base_z(v.co.x) for v in bm.verts)
    thickness_ok = (abs(max_thickness-dims['espessura_mm']) < 0.001 and abs(min_thickness)<0.001
                    and measured_thickness is not None and measured_thickness>dims['altura_lateral_mm'])
    report = dict(vertices=len(bm.verts), arestas=len(bm.edges), triangulos=len(bm.faces),
                  arestas_nao_manifold=edges_bad, faces_degeneradas=degenerate,
                  componentes=components, caracteristica_euler=euler,
                  auto_intersecoes=len(intersections), volume_mm3=volume,
                  vao_central_aberto=aperture_empty, moldura_presente=border_present,
                  dimensoes_mm=list(obj.dimensions), dimensoes_corretas=dimensions_ok,
                  flecha_medida_mm=measured_sagitta, curvatura_correta=curvature_ok,
                  espessura_local_no_raio_mm=measured_thickness,
                  espessura_maxima_mm=max_thickness, espessura_correta=thickness_ok)
    report['aprovado'] = (edges_bad == 0 and degenerate == 0 and components == 1 and euler == 0
                          and not intersections and volume > 0 and aperture_empty and border_present
                          and dimensions_ok and curvature_ok and thickness_ok)
    reports[filename] = report
    bm.to_mesh(obj.data)
    bm.free()
    if filename == 'lente.stl':
        main = obj
    else:
        bpy.data.objects.remove(obj, do_unlink=True)

(OUT/'validacao.json').write_text(json.dumps(reports, indent=2)+'\n')
print('VALIDACAO:', json.dumps(reports, indent=2))
assert all(r['aprovado'] for r in reports.values()), 'Malha reprovada; consulte validacao.json'

material = bpy.data.materials.new('Grafite acetinado')
material.use_nodes = True
shader = material.node_tree.nodes.get('Principled BSDF')
shader.inputs['Base Color'].default_value = (0.055, 0.048, 0.038, 1)
shader.inputs['Metallic'].default_value = 0.45
shader.inputs['Roughness'].default_value = 0.28
main.data.materials.append(material)
for polygon in main.data.polygons:
    polygon.use_smooth = True
# Marca somente o encontro do verso com os lados; a frente é abaulada contínua.
bm = bmesh.new()
bm.from_mesh(main.data)
bm.normal_update()
for edge in bm.edges:
    if edge.is_manifold and edge.calc_face_angle()>math.radians(45):
        edge.smooth = False
bm.to_mesh(main.data)
bm.free()

scene.render.engine = 'CYCLES'
scene.cycles.samples = 96
scene.cycles.use_denoising = False
scene.render.resolution_x = 1200
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.film_transparent = True
scene.world.color = (0.3, 0.3, 0.3)
scene.view_settings.view_transform = 'AgX'

for name, position, power, size in [
    ('Principal', (-90, 50, 180), 650000, 140),
    ('Preenchimento', (130, 50, 130), 400000, 110),
    ('Recorte', (-30, -100, 90), 450000, 100),
]:
    light = bpy.data.lights.new(name, 'AREA')
    light.energy, light.shape, light.size = power, 'DISK', size
    obj = bpy.data.objects.new(name, light)
    scene.collection.objects.link(obj)
    obj.location = position
    obj.rotation_euler = (Vector((0,0,0))-obj.location).to_track_quat('-Z','Y').to_euler()

camera_data = bpy.data.cameras.new('Camera')
camera = bpy.data.objects.new('Camera', camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
camera_data.type = 'ORTHO'
camera_data.ortho_scale = max(dims['largura_mm'],dims['altura_mm'])*1.22

for name, position in [('vista_frontal', (0,0,300)), ('vista_3d', (80,-160,230)),
                       ('vista_curvatura', (0,-300,65))]:
    camera.location = position
    camera.rotation_euler = (Vector((0,0,1))-camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath = str(OUT/(name+'.png'))
    bpy.ops.render.render(write_still=True)

# O espaçamento entre as duas peças é apenas ilustrativo; não cria uma ponte.
main.location.x = -51
other = bpy.data.objects.new('Lente espelhada - apresentação',main.data.copy())
scene.collection.objects.link(other)
other.scale.x = -1
other.location.x = 51
camera.location = (0,0,320)
camera.rotation_euler = (Vector((0,0,1))-camera.location).to_track_quat('-Z','Y').to_euler()
camera_data.ortho_scale = 218
scene.render.resolution_x = 1600
scene.render.resolution_y = 800
scene.render.filepath = str(OUT/'vista_par.png')
bpy.ops.render.render(write_still=True)
bpy.data.objects.remove(other,do_unlink=True)
main.location.x = 0
camera_data.ortho_scale = max(dims['largura_mm'],dims['altura_mm'])*1.22
camera.location = (80,-160,230)
camera.rotation_euler = (Vector((0,0,1))-camera.location).to_track_quat('-Z','Y').to_euler()
scene.render.resolution_x = scene.render.resolution_y = 1200
scene.render.filepath = str(OUT/'vista_3d.png')
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'lente.blend'))

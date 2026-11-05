#!/usr/bin/env python3
"""Gera STL e OpenSCAD em mm, sem dependências externas.

O contorno é uma aproximação manual da fotografia, e não uma medição 3D.
"""
import argparse
import json
import math
from pathlib import Path
import struct


# Olho mais visível da foto da máscara. Curvas em coordenadas da referência,
# antes da normalização para as medidas frontais solicitadas de 90 x 65 mm.
OUTER = [
    [(294, 75), (298, 85), (310, 95), (326, 104)],
    [(326, 104), (353, 120), (385, 140), (409, 154)],
    [(409, 154), (414, 157), (414, 161), (409, 167)],
    [(409, 167), (394, 184), (377, 200), (362, 209)],
    [(362, 209), (356, 213), (351, 214), (344, 208)],
    [(344, 208), (314, 188), (291, 151), (289, 117)],
    [(289, 117), (287, 101), (289, 84), (291, 77)],
    [(291, 77), (292, 74), (293, 73), (294, 75)],
]
INNER = [
    [(302, 99), (309, 104), (320, 110), (332, 118)],
    [(332, 118), (356, 132), (380, 145), (398, 156)],
    [(398, 156), (402, 158), (403, 160), (398, 165)],
    [(398, 165), (386, 179), (370, 194), (357, 201)],
    [(357, 201), (354, 203), (351, 202), (347, 199)],
    [(347, 199), (321, 181), (303, 151), (300, 122)],
    [(300, 122), (299, 113), (299, 104), (300, 100)],
    [(300, 100), (300, 98), (301, 98), (302, 99)],
]


def bezier_outline(curves, samples=100):
    points = []
    for curve in curves:
        for step in range(samples):
            t = step / samples
            a = [(1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3]
            points.append(tuple(sum(a[k]*curve[k][axis] for k in range(4)) for axis in (0, 1)))
    return points


def cross2(a, b):
    return a[0]*b[1] - a[1]*b[0]


def radial_samples(polygon, count):
    # Ambos os contornos são estrelados em relação a este ponto, dentro do vão.
    center = (345, 155)
    out = []
    for i in range(count):
        theta = 2*math.pi*i/count
        direction = (math.cos(theta), math.sin(theta))
        hits = []
        for j, p in enumerate(polygon):
            q = polygon[(j+1) % len(polygon)]
            edge = (q[0]-p[0], q[1]-p[1])
            rel = (p[0]-center[0], p[1]-center[1])
            den = cross2(direction, edge)
            if abs(den) < 1e-12:
                continue
            distance, u = cross2(rel, edge)/den, cross2(rel, direction)/den
            if distance > 0 and 0 <= u < 1:
                hits.append(distance)
        if len(hits) != 1:
            raise ValueError(f"Contorno não estrelado no raio {i}: {hits}")
        out.append((center[0]+direction[0]*hits[0], center[1]+direction[1]*hits[0]))
    return out


def curvature(x, width, sagitta):
    if sagitta == 0:
        return 0
    radius = (width*width/4+sagitta*sagitta)/(2*sagitta)
    return math.sqrt(max(0, radius*radius-x*x))-(radius-sagitta)


def make_mesh(outer, inner, thickness, edge_height, width, sagitta, mirror, sections):
    # Perfil elíptico abaulado: lados baixos, crista central, sem faixa plana.
    n = len(outer)
    # Cada par (u,z) é uma volta completa ao redor da abertura. u=0 é o
    # contorno externo; u=1 é o interno. Fecha-se o perfil pelo verso.
    profile = [(0, 0)]
    profile += [((1-math.cos(math.pi*k/sections))/2,
                 edge_height+(thickness-edge_height)*math.sin(math.pi*k/sections))
                for k in range(sections+1)]
    profile += [(1, 0)] + [(1-k/8, 0) for k in range(1, 8)]
    vertices = []
    for u,z in profile:
        for a,b in zip(outer,inner):
            x,y = [(1-u)*a[k]+u*b[k] for k in (0,1)]
            vertices.append((-x if mirror else x,y,z+curvature(x,width,sagitta)))
    faces = []
    for layer in range(len(profile)):
        for i in range(n):
            j, next_layer = (i+1)%n,(layer+1)%len(profile)
            a,b,c,d = layer*n+i,layer*n+j,next_layer*n+j,next_layer*n+i
            faces.extend([(a,b,c),(a,c,d)])
    if mirror:
        faces = [tuple(reversed(face)) for face in faces]
    return vertices, faces


def write_stl(path, vertices, faces):
    with path.open('wb') as file:
        file.write(b'Lente Miranha - mm - centro vazado'.ljust(80, b' '))
        file.write(struct.pack('<I', len(faces)))
        for indices in faces:
            a, b, c = [vertices[i] for i in indices]
            u, v = [b[k]-a[k] for k in range(3)], [c[k]-a[k] for k in range(3)]
            normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
            length = math.sqrt(sum(x*x for x in normal))
            normal = tuple(x/length for x in normal)
            file.write(struct.pack('<12fH', *normal, *a, *b, *c, 0))


def write_scad(path, outer, inner, width, height, thickness, edge_height, sagitta, sections):
    source = '''// Unidades: mm. Contorno baseado na foto da máscara; centro totalmente vazado.
// Ajuste os parâmetros e pressione F6. Arquivo > Exportar > Exportar como STL.
largura_mm = WIDTH;
altura_mm = HEIGHT;
espessura_mm = THICKNESS;
altura_lateral_mm = EDGE_HEIGHT; // Espessura junto às bordas interna/externa.
secoes_perfil = SECTIONS; // Par; a frente tem um perfil elíptico arredondado.
flecha_mm = SAGITTA; // Elevação do centro sobre as extremidades, ao longo de X.
espelhar = false;

'''.replace('EDGE_HEIGHT', str(edge_height)).replace('WIDTH', str(width)).replace('HEIGHT', str(height)).replace('THICKNESS', str(thickness)).replace('SAGITTA', str(sagitta)).replace('SECTIONS',str(sections))
    for name, values in [('externo', outer), ('interno', inner)]:
        source += name+' = '+json.dumps([[round(x, 8), round(y, 8)] for x, y in values], separators=(',', ':'))+';\n'
    source += '''
assert(largura_mm > 0 && altura_mm > 0 && espessura_mm > 0, "Dimensões devem ser positivas.");
assert(altura_lateral_mm > 0 && altura_lateral_mm < espessura_mm,
       "A altura lateral deve estar entre zero e a espessura máxima.");
assert(secoes_perfil >= 12 && secoes_perfil%2==0, "Use um número par de seções, no mínimo 12.");
assert(flecha_mm >= 0 && flecha_mm < largura_mm/2, "Flecha fora do intervalo permitido.");
n = len(externo);
externo_mm = [for(p=externo) [p[0]*largura_mm,p[1]*altura_mm]];
interno_mm = [for(p=interno) [p[0]*largura_mm,p[1]*altura_mm]];
function curva(x) = flecha_mm == 0 ? 0 :
    let(r=(largura_mm*largura_mm/4+flecha_mm*flecha_mm)/(2*flecha_mm))
    sqrt(max(0,r*r-x*x))-(r-flecha_mm);
perfil = concat([[0,0]],[for(k=[0:secoes_perfil])
    [(1-cos(k*180/secoes_perfil))/2,
     altura_lateral_mm+(espessura_mm-altura_lateral_mm)*sin(k*180/secoes_perfil)]],
    [[1,0]],[for(k=[1:7]) [1-k/8,0]]);
m = len(perfil);
vertices = [for(level=perfil,i=[0:n-1])
    let(p=externo_mm[i]*(1-level[0])+interno_mm[i]*level[0])
    [espelhar ? -p[0] : p[0],p[1],level[1]+curva(p[0])]];
quads = [for(l=[0:m-1],i=[0:n-1]) let(j=(i+1)%n,k=(l+1)%m)
    [l*n+i,l*n+j,k*n+j,k*n+i]];
triangulos = [for(q=quads) each [[q[0],q[1],q[2]],[q[0],q[2],q[3]]]];
// OpenSCAD usa orientação de faces oposta à convenção STL.
faces_scad = [for(t=triangulos) espelhar ? t : [t[2],t[1],t[0]]];
polyhedron(points=vertices, faces=faces_scad, convexity=10);
'''
    path.write_text(source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--largura', type=float, default=90)
    parser.add_argument('--altura', type=float, default=65)
    parser.add_argument('--flecha', type=float, default=10)
    parser.add_argument('--espessura', type=float, default=4)
    parser.add_argument('--borda', type=float, default=1.2)
    parser.add_argument('--secoes', type=int, default=24)
    parser.add_argument('--amostras', type=int, default=720)
    args = parser.parse_args()
    if not (args.largura > 0 and args.altura > 0 and 0 <= args.flecha < args.largura/2
            and 0 < args.borda < args.espessura and args.secoes>=12 and args.secoes%2==0 and args.amostras>=128):
        parser.error('Use dimensões positivas, 0 <= flecha < largura/2, 0 < borda < espessura, seções pares >=12 e amostras >=128.')
    outdir = Path(__file__).resolve().parents[1]/'modelo'
    outdir.mkdir(exist_ok=True)
    outer, inner = [radial_samples(bezier_outline(curves), args.amostras) for curves in (OUTER, INNER)]
    # A inversão de Y devolve a mesma orientação visual da fotografia.
    # Invertemos também a ordem para manter os dois contornos anti-horários.
    xmin, xmax = min(p[0] for p in outer), max(p[0] for p in outer)
    ymin, ymax = min(p[1] for p in outer), max(p[1] for p in outer)
    cx, cy = (xmin+xmax)/2, (ymin+ymax)/2
    outer, inner = [[((p[0]-cx)/(xmax-xmin), (cy-p[1])/(ymax-ymin)) for p in points[::-1]] for points in (outer, inner)]
    outer_mm, inner_mm = [[(p[0]*args.largura,p[1]*args.altura) for p in points] for points in (outer,inner)]
    for mirrored, name in [(False, 'lente'), (True, 'lente_espelhada')]:
        vertices, faces = make_mesh(outer_mm,inner_mm,args.espessura,args.borda,args.largura,args.flecha,mirrored,args.secoes)
        write_stl(outdir/(name+'.stl'), vertices, faces)
    write_scad(outdir/'lente_parametrica.scad',outer,inner,args.largura,args.altura,args.espessura,args.borda,args.flecha,args.secoes)
    data = dict(largura_mm=args.largura, altura_mm=args.altura, flecha_mm=args.flecha,
                espessura_mm=args.espessura, altura_lateral_mm=args.borda, perfil_frontal='elíptico abaulado',
                referencia='olho mais visível da fotografia da máscara', versao=3,
                profundidade_total_mm=max(v[2] for v in vertices)-min(v[2] for v in vertices),
                raio_curvatura_mm=(args.largura**2/4+args.flecha**2)/(2*args.flecha) if args.flecha else None,
                espessura_medida_em='Z', eixo_curvatura='X',
                vertices=len(vertices), triangulos=len(faces), plano=args.flecha==0, centro_vazado=True)
    (outdir/'dimensoes.json').write_text(json.dumps(data, indent=2)+'\n')
    (outdir/'contornos.json').write_text(json.dumps(dict(externo=outer, interno=inner)))
    print(json.dumps(data, indent=2))


if __name__ == '__main__':
    main()

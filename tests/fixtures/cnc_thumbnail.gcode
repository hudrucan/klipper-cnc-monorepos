; Fusion CAM preview fixture
; Stock Box:
;   X: Min=0 Max=100 Size=100
;   Y: Min=0 Max=70 Size=70
;   Z: Min=-4 Max=12 Size=16
; Ranges Table:
;   X: Min=10 Max=90 Size=80
;   Y: Min=10 Max=60 Size=50
;   Z: Min=-4 Max=8 Size=12
G21
G90
G0 X10 Y10 Z8
G1 Z-2 F300
G1 X90 Y10 F900
G3 X90 Y60 I0 J25
G1 X10 Y60
G3 X10 Y10 I0 J-25
G0 Z8
G0 X28 Y25
G1 Z-4 F300
G2 X72 Y25 I22 J0 F700
G2 X28 Y25 I-22 J0
G0 Z8
G0 X0 Y0

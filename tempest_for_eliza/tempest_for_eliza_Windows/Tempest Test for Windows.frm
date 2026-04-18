VERSION 5.00
Begin VB.Form Form1 
   AutoRedraw      =   -1  'True
   BorderStyle     =   0  'None
   Caption         =   "Form1"
   ClientHeight    =   3030
   ClientLeft      =   0
   ClientTop       =   0
   ClientWidth     =   4560
   LinkTopic       =   "Form1"
   MaxButton       =   0   'False
   MinButton       =   0   'False
   ScaleHeight     =   202
   ScaleMode       =   3  'Pixel
   ScaleWidth      =   304
   ShowInTaskbar   =   0   'False
   StartUpPosition =   3  'Windows Default
   WindowState     =   2  'Maximized
   Begin VB.Timer Timer1 
      Enabled         =   0   'False
      Interval        =   1
      Left            =   1680
      Top             =   1320
   End
End
Attribute VB_Name = "Form1"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Private Declare Sub FillMemory Lib "kernel32.dll" Alias "RtlFillMemory" (ByRef Destination As Any, ByVal Length As Long, ByVal Fill As Byte)
Private Declare Function SetDIBits Lib "gdi32.dll" (ByVal hDC As Long, ByVal hBitmap As Long, ByVal nStartScan As Long, ByVal nNumScans As Long, ByRef lpBits As Any, ByRef lpBI As BITMAPINFO, ByVal wUsage As Long) As Long
Private Declare Sub Sleep Lib "kernel32.dll" (ByVal dwMilliseconds As Long)
Private Declare Function SetWindowPos Lib "user32.dll" (ByVal hWnd As Long, ByVal hWndInsertAfter As Long, ByVal x As Long, ByVal y As Long, ByVal cx As Long, ByVal cy As Long, ByVal wFlags As Long) As Long
Private Declare Function GetAsyncKeyState Lib "user32.dll" (ByVal vKey As Long) As Integer
Private Declare Function ShowCursor Lib "user32.dll" (ByVal bShow As Long) As Long


Private Type BITMAPINFOHEADER
    biSize As Long
    biWidth As Long
    biHeight As Long
    biPlanes As Integer
    biBitCount As Integer
    biCompression As Long
    biSizeImage As Long
    biXPelsPerMeter As Long
    biYPelsPerMeter As Long
    biClrUsed As Long
    biClrImportant As Long
End Type

Private Type RGBQUAD
    rgbBlue As Byte
    rgbGreen As Byte
    rgbRed As Byte
    rgbReserved As Byte
End Type

Private Type BITMAPINFO
    bmiHeader As BITMAPINFOHEADER
    bmiColors(255) As RGBQUAD
End Type


Dim PicW As Long
Dim PicH As Long
Dim Pix() As Byte
Dim BMI As BITMAPINFO

Private Type Note
    Freqency As Single
    Duration As Long
End Type

Dim Song() As Note

Dim ProgQuit As Boolean

Private Sub Form_Activate()
Dim y As Long
Dim n As Long
Dim z As Byte
Dim Freq As Single
Dim FrameRate As Long
Dim FrameDuration As Single
Dim LineDuration As Single
Dim LineRate As Single

FrameRate = 60
FrameDuration = 1 / FrameRate
LineDuration = FrameDuration / PicH
LineRate = 1 / LineDuration

SetWindowPos Me.hWnd, -1, 0, 0, 0, 0, &H201

For n = 0 To UBound(Song)
    Freq = Song(n).Freqency
    For y = 0 To PicH - 1
        FillMemory Pix(0, y), PicW, Sgn(Sin(2 * 3.14159 * Freq * y / LineRate)) * 127.5 + 127.5
    Next y
    SetDIBits Me.hDC, Me.Image.Handle, 0, PicH, Pix(0, 0), BMI, 0
    Refresh
    Sleep Song(n).Duration
    DoEvents
    If ProgQuit Then Exit Sub
Next n
Unload Me
End Sub

Private Sub Form_Load()
Dim i As Long
Dim NotesStr As String

ChDir App.Path

PicW = Screen.Width / 15
PicH = Screen.Height / 15
ReDim Pix(PicW - 1, PicH - 1)
With BMI
    With .bmiHeader
        .biSize = 40
        .biPlanes = 1
        .biBitCount = 8
        .biClrUsed = 256
        .biClrImportant = 256
        .biWidth = PicW
        .biHeight = -PicH
    End With
    For i = 0 To 255
        With .bmiColors(i)
            .rgbRed = i
            .rgbGreen = i
            .rgbBlue = i
        End With
    Next i
End With

Open "song.txt" For Binary Access Read As #1
NotesStr = String$(LOF(1), vbNullChar)
Get #1, 1, NotesStr
Close #1

Song() = String2Notes(NotesStr, 300)

GetAsyncKeyState vbKeyEscape
Timer1.Enabled = True
ShowCursor 0
End Sub


Private Function String2Notes(ByVal NotesStr As String, ByVal Duration As Long) As Note()
Dim NoteStrings() As String
Dim Notes() As Note
Dim n As Long

NoteStrings() = Split(NotesStr, " ")
ReDim Notes(UBound(NoteStrings))
For n = 0 To UBound(Notes)
    With Notes(n)
        Select Case NoteStrings(n)
            Case "."
                .Freqency = 0
                .Duration = Duration / 2
            Case "-"
                .Freqency = Notes(n - 1).Freqency
                .Duration = Duration
            Case Else
                .Freqency = Note2Freq(NoteStrings(n))
                .Duration = Duration
        End Select
    End With
Next n
String2Notes = Notes()
End Function

Private Function Note2Freq(ByVal NoteName As String) As Single
Select Case LCase$(NoteName)
    Case "c0"
        Note2Freq = 16.35
    Case "c#0", "db0"
        Note2Freq = 17.32
    Case "d0"
        Note2Freq = 18.35
    Case "d#0", "eb0"
        Note2Freq = 19.45
    Case "e0"
        Note2Freq = 20.6
    Case "f0"
        Note2Freq = 21.83
    Case "f#0", "gb0"
        Note2Freq = 23.12
    Case "g0"
        Note2Freq = 24.5
    Case "g#0", "ab0"
        Note2Freq = 25.96
    Case "a0"
        Note2Freq = 27.5
    Case "a#0", "bb0"
        Note2Freq = 29.14
    Case "b0"
        Note2Freq = 30.87
    
    Case "c1"
        Note2Freq = 32.7
    Case "c#1", "db1"
        Note2Freq = 34.65
    Case "d1"
        Note2Freq = 36.71
    Case "d#1", "eb1"
        Note2Freq = 38.89
    Case "e1"
        Note2Freq = 41.2
    Case "f1"
        Note2Freq = 43.65
    Case "f#1", "gb1"
        Note2Freq = 46.25
    Case "g1"
        Note2Freq = 49
    Case "g#1", "ab1"
        Note2Freq = 51.91
    Case "a1"
        Note2Freq = 55
    Case "a#1", "bb1"
        Note2Freq = 58.27
    Case "b1"
        Note2Freq = 61.74
    
    Case "c2"
        Note2Freq = 65.41
    Case "c#2", "db2"
        Note2Freq = 69.3
    Case "d2"
        Note2Freq = 73.42
    Case "d#2", "eb2"
        Note2Freq = 77.78
    Case "e2"
        Note2Freq = 82.41
    Case "f2"
        Note2Freq = 87.31
    Case "f#2", "gb2"
        Note2Freq = 92.5
    Case "g2"
        Note2Freq = 98
    Case "g#2", "ab2"
        Note2Freq = 103.83
    Case "a2"
        Note2Freq = 110
    Case "a#2", "bb2"
        Note2Freq = 116.54
    Case "b2"
        Note2Freq = 123.47
    
    Case "c3"
        Note2Freq = 130.81
    Case "c#3", "db3"
        Note2Freq = 138.59
    Case "d3"
        Note2Freq = 146.83
    Case "d#3", "eb3"
        Note2Freq = 155.56
    Case "e3"
        Note2Freq = 164.81
    Case "f3"
        Note2Freq = 174.61
    Case "f#3", "gb3"
        Note2Freq = 185
    Case "g3"
        Note2Freq = 196
    Case "g#3", "ab3"
        Note2Freq = 207.65
    Case "a3"
        Note2Freq = 220
    Case "a#3", "bb3"
        Note2Freq = 233.08
    Case "b3"
        Note2Freq = 246.94
    
    Case "c4"
        Note2Freq = 261.63
    Case "c#4", "db4"
        Note2Freq = 277.18
    Case "d4"
        Note2Freq = 293.66
    Case "d#4", "eb4"
        Note2Freq = 311.13
    Case "e4"
        Note2Freq = 329.63
    Case "f4"
        Note2Freq = 349.23
    Case "f#4", "gb4"
        Note2Freq = 369.99
    Case "g4"
        Note2Freq = 392
    Case "g#4", "ab4"
        Note2Freq = 415.3
    Case "a4"
        Note2Freq = 440
    Case "a#4", "bb4"
        Note2Freq = 466.16
    Case "b4"
        Note2Freq = 493.88
    
    Case "c5"
        Note2Freq = 523.25
    Case "c#5", "db5"
        Note2Freq = 554.37
    Case "d5"
        Note2Freq = 587.33
    Case "d#5", "eb5"
        Note2Freq = 622.25
    Case "e5"
        Note2Freq = 659.25
    Case "f5"
        Note2Freq = 698.46
    Case "f#5", "gb5"
        Note2Freq = 739.99
    Case "g5"
        Note2Freq = 783.99
    Case "g#5", "ab5"
        Note2Freq = 830.61
    Case "a5"
        Note2Freq = 880
    Case "a#5", "bb5"
        Note2Freq = 932.33
    Case "b5"
        Note2Freq = 987.77
    
    Case "c6"
        Note2Freq = 1046.5
    Case "c#6", "db6"
        Note2Freq = 1108.73
    Case "d6"
        Note2Freq = 1174.66
    Case "d#6", "eb6"
        Note2Freq = 1244.51
    Case "e6"
        Note2Freq = 1318.51
    Case "f6"
        Note2Freq = 1396.91
    Case "f#6", "gb6"
        Note2Freq = 1479.98
    Case "g6"
        Note2Freq = 1567.98
    Case "g#6", "ab6"
        Note2Freq = 1661.22
    Case "a6"
        Note2Freq = 1760
    Case "a#6", "bb6"
        Note2Freq = 1864.66
    Case "b6"
        Note2Freq = 1975.53
    
    Case "c7"
        Note2Freq = 2093
    Case "c#7", "db7"
        Note2Freq = 2217.46
    Case "d7"
        Note2Freq = 2349.32
    Case "d#7", "eb7"
        Note2Freq = 2489.02
    Case "e7"
        Note2Freq = 2637.02
    Case "f7"
        Note2Freq = 2793.83
    Case "f#7", "gb7"
        Note2Freq = 2959.96
    Case "g7"
        Note2Freq = 3135.96
    Case "g#7", "ab7"
        Note2Freq = 3322.44
    Case "a7"
        Note2Freq = 3520
    Case "a#7", "bb7"
        Note2Freq = 3729.31
    Case "b7"
        Note2Freq = 3951.07
    
    Case "c8"
        Note2Freq = 4186.01
    Case "c#8", "db8"
        Note2Freq = 4434.92
    Case "d8"
        Note2Freq = 4698.63
    Case "d#8", "eb8"
        Note2Freq = 4978.03
    Case "e8"
        Note2Freq = 5274.04
    Case "f8"
        Note2Freq = 5587.65
    Case "f#8", "gb8"
        Note2Freq = 5919.91
    Case "g8"
        Note2Freq = 6271.93
    Case "g#8", "ab8"
        Note2Freq = 6644.88
    Case "a8"
        Note2Freq = 7040
    Case "a#8", "bb8"
        Note2Freq = 7458.62
    Case "b8"
        Note2Freq = 7902.13
    
    Case Else
        Stop
End Select
End Function


Private Sub Form_Unload(Cancel As Integer)
ShowCursor 1
End Sub

Private Sub Timer1_Timer()
If (GetAsyncKeyState(vbKeyEscape) And 1) = 1 Then
    ProgQuit = True
    Unload Me
End If
End Sub

import serial

ser = serial.Serial('COM3', baudrate=9600, bytesize=7, parity='E', stopbits=1, timeout=2)
ser.write(b'/?!\r\n')
response = ser.read(64)
print("Response:", response.decode(errors='ignore'))

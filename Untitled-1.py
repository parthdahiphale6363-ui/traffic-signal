a = int(input("enter number a "))
b = int(input("enter number b "))
c = int(input("enter number c "))
if a >= b and a >= c:
    print("a is the greatest")
elif b >= a and b >= c:
    print("b is the greatest")
else:
    print("c is the greatest")
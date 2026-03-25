math = int(input("Enter marks of maths :"))
chem = int(input("Enter marks of chem :"))
phy = int(input("Enter marks of phy :"))
total=math+chem+phy
print("total",total)
percentage=(total/3.0)
print("percentage",percentage)
if percentage>=60:
    print("eligible for the placement drive");
else:
    print("not eligible for the placement drive");
    
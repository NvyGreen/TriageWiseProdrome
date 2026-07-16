from datetime import date

def age_from_dob(dob: date, as_of: date | None = None) -> int:
    ref = as_of or date.today()
    return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
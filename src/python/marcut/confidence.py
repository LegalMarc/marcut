def combine(b,agreements=0,ctx_boost=0.0,fuzzy_penalty=0.0):
 c=b+0.07*agreements+ctx_boost-fuzzy_penalty
 return max(0.0,min(1.0,c))

def low_conf(c):
 return c<0.88

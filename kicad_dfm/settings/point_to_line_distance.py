from math import sqrt

LINE_WIDTH_EXTEN = 80000


def point_to_line_distance(p, line):
    """计算点到线段的垂直距离"""
    C = (line["start_x"], line["start_y"])
    D = (line["end_x"], line["end_y"])

    # 计算分子部分
    numerator = abs((D[1] - C[1]) * (p[0] - C[0]) - (D[0] - C[0]) * (p[1] - C[1]))

    # 计算分母部分
    denominator = sqrt((D[1] - C[1]) ** 2 + (D[0] - C[0]) ** 2)

    # 避免除以零
    if denominator == 0:
        return float("inf")  # 如果线段的端点相同，返回无穷大距离
    distance = numerator / denominator

    # 判断线段是否水平或垂直
    if (D[1] - C[1]) == 0:  # 线段CD水平, 垂足 P' 的坐标
        P_prime_x = p[0]
        P_prime_y = D[1]
    elif (D[0] - C[0]) == 0:  # 线段垂直, 垂足 P' 的坐标
        P_prime_x = D[0]
        P_prime_y = p[1]
    else:
        factor_denominator = (D[0] - C[0]) ** 2 + (D[1] - C[1]) ** 2
        factor = (
            (p[0] - C[0]) * (D[0] - C[0]) + (p[1] - C[1]) * (D[1] - C[1])
        ) / factor_denominator
        P_prime_x = C[0] + factor * (D[0] - C[0])
        P_prime_y = C[1] + factor * (D[1] - C[1])

    # 判断垂足 P' 是否在线段上( 前两条判断斜率为正的情况，后两条判断斜率为负的情况)
    is_on_segment = (
        (
            (C[0] - LINE_WIDTH_EXTEN <= P_prime_x <= D[0] + LINE_WIDTH_EXTEN)
            and (C[1] - LINE_WIDTH_EXTEN <= P_prime_y <= D[1] + LINE_WIDTH_EXTEN)
        )
        or (
            (D[0] - LINE_WIDTH_EXTEN <= P_prime_x <= C[0] + LINE_WIDTH_EXTEN)
            and (D[1] - LINE_WIDTH_EXTEN <= P_prime_y <= C[1] + LINE_WIDTH_EXTEN)
        )
        or (
            (D[0] - LINE_WIDTH_EXTEN <= P_prime_x <= C[0] + LINE_WIDTH_EXTEN)
            and (C[1] - LINE_WIDTH_EXTEN <= P_prime_y <= D[1] + LINE_WIDTH_EXTEN)
        )
        or (
            (C[0] - LINE_WIDTH_EXTEN <= P_prime_x <= D[0] + LINE_WIDTH_EXTEN)
            and (D[1] - LINE_WIDTH_EXTEN <= P_prime_y <= C[1] + LINE_WIDTH_EXTEN)
        )
    )
    if is_on_segment:
        return distance
    else:
        return 1000000

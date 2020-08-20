
import wave as wave
import pyroomacoustics as pa
import numpy as np
import scipy.signal as sp
import scipy as scipy

#順列計算に使用
import itertools
import time

#A: ...mn
#B: ...ij
#AとBの最後の二軸以外の次元は一致していることを前提とする
def batch_kron(A,B):
 if np.shape(A)[:-2]!=np.shape(B)[:-2]:
     print("error")
     return None
 else:
    return(np.reshape(np.einsum("...mn,...ij->...minj",A,B),np.shape(A)[:-2]+(np.shape(A)[-2]*np.shape(B)[-2],np.shape(A)[-1]*np.shape(B)[-1])))


#x:入力信号( M, Nk, Lt)
#D:遅延フレーム数
#Lh:残響除去フィルタのタップ長
#return x_bar: 過去のマイク入力信号(Lh,M,Nk,Lt)
def make_x_bar(x,D,Lh):
    
    #フレーム数を取得
    Lt=np.shape(x)[2]

    #過去のマイク入力信号の配列を準備
    x_bar=np.zeros(shape=(Lh,)+np.shape(x),dtype=np.complex)

    for tau in range(Lh):
        x_bar[tau,...,tau+D:]=x[:,:,:-(tau+D)]

    return(x_bar)


#コントラスト関数の微分（球対称多次元ラプラス分布を仮定）
#s_hat: 分離信号(M, Nk, Lt)
def phi_multivariate_laplacian(s_hat):

    power=np.square(np.abs(s_hat))
    norm=np.sqrt(np.sum(power,axis=1,keepdims=True))

    phi=s_hat/np.maximum(norm,1.e-18)
    return(phi)

#コントラスト関数の微分（球対称ラプラス分布を仮定）
#s_hat: 分離信号(M, Nk, Lt)
def phi_laplacian(s_hat):

    norm=np.abs(s_hat)
    phi=s_hat/np.maximum(norm,1.e-18)
    return(phi)

#コントラスト関数（球対称ラプラス分布を仮定）
#s_hat: 分離信号(M, Nk, Lt)
def contrast_laplacian(s_hat):

    norm=2.*np.abs(s_hat)
    
    return(norm)

#コントラスト関数（球対称多次元ラプラス分布を仮定）
#s_hat: 分離信号(M, Nk, Lt)
def contrast_multivariate_laplacian(s_hat):
    power=np.square(np.abs(s_hat))
    norm=2.*np.sqrt(np.sum(power,axis=1,keepdims=True))
  
    return(norm)

# X#Yを計算
def geometric_mean(X,Y):

    invX=np.linalg.pinv(X)
    invX_Y=np.matmul(invX,Y)
    sqrt_invX_Y=scipy.linalg.sqrtm(invX_Y)
    res=np.matmul(X,sqrt_invX_Y)
    return(res)

#IP法によるLGMのパラメータ推定法
#x:入力信号( M, Nk, Lt)
#Ns: 音源数
#n_iterations: 繰り返しステップ数
#return R 共分散行列(Nk,Ns,M,M) v 時間周波数分散(Nk,Ns,Lt),c_bar 音源分離信号(M,Ns,Nk,Lt), cost_buff コスト (T)
def execute_mm_lgm(x,Ns=2,n_iterations=20):
    
    #マイクロホン数・周波数・フレーム数を取得する
    M=np.shape(x)[0]
    Nk=np.shape(x)[1]
    Lt=np.shape(x)[2]

    #Rとvを初期化する
    mask=np.random.uniform(size=Nk*Ns*Lt)
    mask=np.reshape(mask,(Nk,Ns,Lt))
    R=np.einsum("kst,mkt,nkt->kstmn",mask,x,np.conjugate(x))
    R=np.average(R,axis=2)
    v=np.random.uniform(size=Nk*Ns*Lt)
    v=np.reshape(v,(Nk,Ns,Lt))

    cost_buff=[]
    for t in range(n_iterations):
        
        #入力信号の共分散行列を求める
        vR=np.einsum("kst,ksmn->kstmn",v,R)
        V=np.sum(vR,axis=1)
        V_inverse=np.linalg.pinv(V)

        #コスト計算
        cost=np.sum(np.einsum("mkt,ktmn,nkt->kt",np.conjugate(x),V_inverse,x) +np.log(np.abs(np.linalg.det(V))))
        cost/=np.float(Lt)
        cost=np.real(cost)
        cost_buff.append(cost)

        #パラメータを更新
        
        #Rの更新
        V_inverseX=np.einsum('ktmn,nkt->ktm',V_inverse,x)
        V_inverseXV_inverseX=np.einsum('ktm,ktn->ktmn',V_inverseX,np.conjugate(V_inverseX))
        A=np.einsum('kst,ktmn->ksmn',v,V_inverse)
        B=np.einsum('kst,ktmn->ksmn',v,V_inverseXV_inverseX)
        RBR=np.einsum('ksmn,ksni,ksij->ksmj',R,B,R)
        invA=np.linalg.pinv(A)
        A_RBR=np.matmul(A,RBR)
        R=np.concatenate([np.concatenate([np.matmul(invA[k,s,...],scipy.linalg.sqrtm(A_RBR[k,s,...]))[None,None,...] for k in range(Nk)],axis=0) for s in range(Ns)],axis=1)
        R=(R+np.transpose(np.conjugate(R),[0,1,3,2]))/(2.0+0.0j)

        #vの更新
        v=v*np.sqrt(np.einsum('ktm,ktn,ksnm->kst',V_inverseX,np.conjugate(V_inverseX),R)/np.maximum(np.einsum('ktmn,ksnm->kst',V_inverse,R) ,1.e-18))

       
    vR=np.einsum("kst,ksmn->kstmn",v,R)
    V=np.sum(vR,axis=1)
    V_inverse=np.linalg.pinv(V)
    Wmwf=np.einsum("kstmi,ktin->kstmn",vR,V_inverse)

    #音源分離信号を得る
    c_bar=np.einsum('kstmn,nkt->mskt',Wmwf,x)

    return(R,v,c_bar,cost_buff)

#LGMの音源分離と残響除去のパラメータ推定法
#x:入力信号( M, Nk, Lt)
#x_bar:過去のマイク入力信号(Lh,M, Nk, Lt)
#Ns: 音源数
#n_iterations: 繰り返しステップ数
#return R 共分散行列(Nk,Ns,M,M) v 時間周波数分散(Nk,Ns,Lt),c_bar 音源分離信号(M,Ns,Nk,Lt), cost_buff コスト (T)
def execute_mm_lgm_dereverb(x,x_bar,Ns=2,n_iterations=20):
    
    #マイクロホン数・周波数・フレーム数を取得する
    M=np.shape(x)[0]
    Nk=np.shape(x)[1]
    Lt=np.shape(x)[2]
    Lh=np.shape(x_bar)[0]

    x_bar=np.reshape(x_bar,[Lh*M,Nk,Lt])

    #Rとvを初期化する
    mask=np.random.uniform(size=Nk*Ns*Lt)
    mask=np.reshape(mask,(Nk,Ns,Lt))
    R=np.einsum("kst,mkt,nkt->kstmn",mask,x,np.conjugate(x))
    R=np.average(R,axis=2)
    v=np.random.uniform(size=Nk*Ns*Lt)
    v=np.reshape(v,(Nk,Ns,Lt))

    #共分散行列を計算
    x_bar_x_bar_H=np.einsum('ikt,jkt->ktij',x_bar,np.conjugate(x_bar))

    #相関行列を計算
    x_bar_x_H=np.einsum('ikt,mkt->ktim',x_bar,np.conjugate(x))

    cost_buff=[]
    for t in range(n_iterations):
        #入力信号の共分散行列を求める
        vR=np.einsum("kst,ksmn->kstmn",v,R)
        
        V=np.sum(vR,axis=1)
        V=V+np.eye(M,M)*1.e-8
        V_inverse=np.linalg.inv(V)
        
        #残響除去フィルタを求める
        x_barx_H_V_inv=np.einsum("ktim,ktmn->kin",x_bar_x_H,V_inverse)

        vec_x_bar_x_HV_inv=np.reshape(np.transpose(x_barx_H_V_inv,[0,2,1]),(Nk,Lh*M*M))
        
        #多次元配列対応版のクロネッカー積
        V_inverse_x_x_H=batch_kron(np.transpose(V_inverse,(0,1,3,2)),x_bar_x_bar_H)

        #vecHを求める
        vec_h=np.einsum("kmr,kr->km",np.linalg.inv(np.sum(V_inverse_x_x_H,axis=1)), vec_x_bar_x_HV_inv)
        
        #行列に戻す
        h=np.transpose(np.reshape(vec_h,(Nk,M,Lh*M)),(0,2,1))

        #残響除去を行う
        x_reverb=np.einsum('kjm,jkt->mkt',np.conjugate(h),x_bar)
        x_dereverb=x-x_reverb
        

        #コスト計算
        cost=np.sum(np.einsum("mkt,ktmn,nkt->kt",np.conjugate(x_dereverb),V_inverse,x_dereverb) +np.log(np.abs(np.linalg.det(V))))
        cost/=np.float(Lt)
        cost=np.real(cost)
        cost_buff.append(cost)
        #print(t,cost)
        #パラメータを更新
        
        #Rの更新
        V_inverseX=np.einsum('ktmn,nkt->ktm',V_inverse,x_dereverb)
        V_inverseXV_inverseX=np.einsum('ktm,ktn->ktmn',V_inverseX,np.conjugate(V_inverseX))
        A=np.einsum('kst,ktmn->ksmn',v,V_inverse)
        B=np.einsum('kst,ktmn->ksmn',v,V_inverseXV_inverseX)
        RBR=np.einsum('ksmn,ksni,ksij->ksmj',R,B,R)
        invA=np.linalg.pinv(A)
        A_RBR=np.matmul(A,RBR)
        R=np.concatenate([np.concatenate([np.matmul(invA[k,s,...],scipy.linalg.sqrtm(A_RBR[k,s,...]))[None,None,...] for k in range(Nk)],axis=0) for s in range(Ns)],axis=1)
        R=(R+np.transpose(np.conjugate(R),[0,1,3,2]))/(2.0+0.0j)

        #vの更新
        v=v*np.sqrt(np.einsum('ktm,ktn,ksnm->kst',V_inverseX,np.conjugate(V_inverseX),R)/np.maximum(np.einsum('ktmn,ksnm->kst',V_inverse,R) ,1.e-18))

       
    vR=np.einsum("kst,ksmn->kstmn",v,R)
    V=np.sum(vR,axis=1)
    V_inverse=np.linalg.pinv(V)
    Wmwf=np.einsum("kstmi,ktin->kstmn",vR,V_inverse)

    #音源分離信号を得る
    c_bar=np.einsum('kstmn,nkt->mskt',Wmwf,x_dereverb)

    return(R,v,c_bar,cost_buff)


#IP法による分離フィルタ更新
#x:入力信号( M, Nk, Lt)
#W: 分離フィルタ(Nk,M,M)
#a: アクティビティ(B,M,Lt)
#b: 基底(Nk,M,B)
#n_iterations: 繰り返しステップ数
#return W 分離フィルタ(Nk,M,M) s_hat 出力信号(M,Nk, Lt),cost_buff コスト (T)
def execute_ip_time_varying_gaussian_ilrma(x,W,a,b,n_iterations=20):
    
    #マイクロホン数・周波数・フレーム数を取得する
    M=np.shape(x)[0]
    Nk=np.shape(x)[1]
    Lt=np.shape(x)[2]

    cost_buff=[]
    for t in range(n_iterations):
        
        #音源分離信号を得る
        s_hat=np.einsum('kmn,nkt->mkt',W,x)
        s_power=np.square(np.abs(s_hat)) 

        #時間周波数分散を更新
        v=np.einsum("bst,ksb->skt",a,b)

        #アクティビティの更新
        a=a*np.sqrt(np.einsum("ksb,skt->bst",b,s_power/np.maximum(v,1.e-18)**2)/np.einsum("ksb,skt->bst",b,1./np.maximum(v,1.e-18)))
        
        #基底の更新
        b=b*np.sqrt(np.einsum("bst,skt->ksb",a,s_power /np.maximum(v,1.e-18)**2) /np.einsum("bst,skt->ksb",a,1./np.maximum(v,1.e-18)))
        
        #時間周波数分散を再度更新
        v=np.einsum("bst,ksb->skt",a,b)

        #コスト計算
        cost=np.sum(np.mean(s_power/np.maximum(v,1.e-18)+np.log(v),axis=-1)) -np.sum(2.*np.log(np.abs(np.linalg.det(W)) ))
        cost_buff.append(cost)

        #IP法による更新
        Q=np.einsum('skt,mkt,nkt->tksmn',1./np.maximum(v,1.e-18),x,np.conjugate(x))
        Q=np.average(Q,axis=0)
        
        for source_index in range(M):
            WQ=np.einsum('kmi,kin->kmn',W,Q[:,source_index,:,:])
            invWQ=np.linalg.pinv(WQ)
            W[:,source_index,:]=np.conjugate(invWQ[:,:,source_index])
            wVw=np.einsum('km,kmn,kn->k',W[:,source_index,:],Q[:,source_index,:,:],np.conjugate(W[:,source_index,:]))
            wVw=np.sqrt(np.abs(wVw))
            W[:,source_index,:]=W[:,source_index,:]/np.maximum(wVw[:,None],1.e-18)

 
    s_hat=np.einsum('kmn,nkt->mkt',W,x)

    return(W,s_hat,cost_buff)

#IP法による分離フィルタ更新
#x:入力信号( M, Nk, Lt)
#x_bar:過去のマイク入力信号(Lh,M, Nk, Lt)
#P: 音源分離・残響除去フィルタ(Nk,M,(Lh+1)*M)
#a: アクティビティ(B,M,Lt)
#b: 基底(Nk,M,B)
#n_iterations: 繰り返しステップ数
#return W 分離フィルタ(Nk,M,M) s_hat 出力信号(M,Nk, Lt),cost_buff コスト (T)
def execute_ip_time_varying_gaussian_ilrma_t(x,x_bar,P,a,b,n_iterations=20):
    
    
    #マイクロホン数・周波数・フレーム数を取得する
    M=np.shape(x)[0]
    Nk=np.shape(x)[1]
    Lt=np.shape(x)[2]
    Lh=np.shape(x_bar)[0]
    
    x_bar=np.reshape(x_bar,[Lh*M,Nk,Lt])
    x_hat=np.concatenate((x,x_bar),axis=0)

    #共分散行列を計算
    x_hat_x_hat_H=np.einsum('ikt,jkt->ktij',x_hat,np.conjugate(x_hat))

    cost_buff=[]
    for t in range(n_iterations):

        #時間周波数分散を更新
        v=np.einsum("bst,ksb->skt",a,b)
        
        #音源分離と残響除去を行う
        s_hat=np.einsum('kmj,jkt->mkt',P,x_hat)
        s_power=np.square(np.abs(s_hat)) 

        #アクティビティの更新
        a=a*np.sqrt(np.einsum("ksb,skt->bst",b,s_power/np.maximum(v,1.e-18)**2)/np.einsum("ksb,skt->bst",b,1./np.maximum(v,1.e-18)))
        
        #基底の更新
        b=b*np.sqrt(np.einsum("bst,skt->ksb",a,s_power /np.maximum(v,1.e-18)**2) /np.einsum("bst,skt->ksb",a,1./np.maximum(v,1.e-18)))
        
        #時間周波数分散を再度更新
        v=np.einsum("bst,ksb->skt",a,b)
        
        #共分散行列を算出
        Q=np.einsum("skt,ktij->tksij",1./np.maximum(v,1.e-18),x_hat_x_hat_H)
        Q=np.average(Q,axis=0)
        Q_inverse=np.linalg.pinv(Q)

        for source_index in range(M):            
            P0=P[:,:,:M]
            P0_inverse=np.linalg.pinv(P0)

            #ステアリングベクトル
            b_steering=P0_inverse[:,:,source_index] 
            
            b_h_Q_inverse_b=np.einsum("km,kmn,kn->k",np.conjugate(b_steering),Q_inverse[:,source_index,:M,:M],b_steering)
            Q_inverse_b=np.einsum("kmn,kn->km",Q_inverse[:,source_index,:,:M],b_steering)
            p=np.einsum("km,k->km",Q_inverse_b,1./np.sqrt(np.maximum(np.abs(b_h_Q_inverse_b),1.e-18)))
            P[:,source_index,:]=np.conjugate(p)
        
        #コスト計算
        cost=np.sum(np.mean(s_power/np.maximum(v,1.e-18)+np.log(v),axis=-1)) -np.sum(2.*np.log(np.abs(np.linalg.det(P[:,:,:M])) ))
        cost_buff.append(cost)
        #print(t,cost)


    s_hat=np.einsum('kmj,jkt->mkt',P,x_hat)
    W=P[:,:,:M]
    return(W,s_hat,cost_buff)


#IP法による分離フィルタ更新
#x:入力信号( M, Nk, Lt)
#x_bar:過去のマイク入力信号(Lh,M, Nk, Lt)
#W: 分離フィルタ(Nk,M,M)
#a: アクティビティ(B,M,Lt)
#b: 基底(Nk,M,B)
#n_iterations: 繰り返しステップ数
#return W 分離フィルタ(Nk,M,M) s_hat 出力信号(M,Nk, Lt),cost_buff コスト (T)
def execute_ip_time_varying_gaussian_ilrma_dereverb(x,x_bar,W,a,b,n_iterations=20):

    #マイクロホン数・周波数・フレーム数を取得する
    M=np.shape(x)[0]
    Nk=np.shape(x)[1]
    Lt=np.shape(x)[2]
    Lh=np.shape(x_bar)[0]
    
    x_bar=np.reshape(x_bar,[Lh*M,Nk,Lt])

    #共分散行列を計算
    x_bar_x_bar_H=np.einsum('ikt,jkt->ktij',x_bar,np.conjugate(x_bar))

    #相関行列を計算
    x_bar_x_H=np.einsum('ikt,mkt->ktim',x_bar,np.conjugate(x))


    cost_buff=[]
    for t in range(n_iterations):

        #時間周波数分散を更新
        v=np.einsum("bst,ksb->skt",a,b)
        
        #入力信号の共分散行列を求める
        V_inverse=np.einsum("skt,ksm,ksn->ktmn",1./np.maximum(v,1.e-18),np.conjugate(W),W)
        
       
        #残響除去フィルタを求める
        x_barx_H_V_inv=np.einsum("ktim,ktmn->kin",x_bar_x_H,V_inverse)

        vec_x_bar_x_HV_inv=np.reshape(np.transpose(x_barx_H_V_inv,[0,2,1]),(Nk,Lh*M*M))
        
        #多次元配列対応版のクロネッカー積
        V_inverse_x_x_H=batch_kron(np.transpose(V_inverse,(0,1,3,2)),x_bar_x_bar_H)

        #vecHを求める
        vec_h=np.einsum("kmr,kr->km",np.linalg.inv(np.sum(V_inverse_x_x_H,axis=1)), vec_x_bar_x_HV_inv)
        
        #行列に戻す
        h=np.transpose(np.reshape(vec_h,(Nk,M,Lh*M)),(0,2,1))

        #残響除去を行う
        x_reverb=np.einsum('kjm,jkt->mkt',np.conjugate(h),x_bar)
        x_dereverb=x-x_reverb
        
        #音源分離信号を得る
        s_hat=np.einsum('kmn,nkt->mkt',W,x_dereverb)
        s_power=np.square(np.abs(s_hat)) 

        #アクティビティの更新
        a=a*np.sqrt(np.einsum("ksb,skt->bst",b,s_power/np.maximum(v,1.e-18)**2)/np.einsum("ksb,skt->bst",b,1./np.maximum(v,1.e-18)))
        
        #基底の更新
        b=b*np.sqrt(np.einsum("bst,skt->ksb",a,s_power /np.maximum(v,1.e-18)**2) /np.einsum("bst,skt->ksb",a,1./np.maximum(v,1.e-18)))
        
        #時間周波数分散を再度更新
        v=np.einsum("bst,ksb->skt",a,b)

        #コスト計算
        cost=np.sum(np.mean(s_power/np.maximum(v,1.e-18)+np.log(v),axis=-1)) -np.sum(2.*np.log(np.abs(np.linalg.det(W)) ))
        cost_buff.append(cost)
        #print(t,cost)

        #IP法による更新
        Q=np.einsum('skt,mkt,nkt->tksmn',1./np.maximum(v,1.e-18),x_dereverb,np.conjugate(x_dereverb))
        Q=np.average(Q,axis=0)
        
        for source_index in range(M):
            WQ=np.einsum('kmi,kin->kmn',W,Q[:,source_index,:,:])
            invWQ=np.linalg.pinv(WQ)
            W[:,source_index,:]=np.conjugate(invWQ[:,:,source_index])
            wVw=np.einsum('km,kmn,kn->k',W[:,source_index,:],Q[:,source_index,:,:],np.conjugate(W[:,source_index,:]))
            wVw=np.sqrt(np.abs(wVw))
            W[:,source_index,:]=W[:,source_index,:]/np.maximum(wVw[:,None],1.e-18)

 
    s_hat=np.einsum('kmn,nkt->mkt',W,x_dereverb)

    return(W,s_hat,cost_buff)

#周波数間の振幅相関に基づくパーミュテーション解法
#s_hat: M,Nk,Lt
#return permutation_index_result：周波数毎のパーミュテーション解 
def solver_inter_frequency_permutation(s_hat):
    n_sources=np.shape(s_hat)[0]
    n_freqs=np.shape(s_hat)[1]
    n_frames=np.shape(s_hat)[2]

    s_hat_abs=np.abs(s_hat)

    norm_amp=np.sqrt(np.sum(np.square(s_hat_abs),axis=0,keepdims=True))
    s_hat_abs=s_hat_abs/np.maximum(norm_amp,1.e-18)

    spectral_similarity=np.einsum('mkt,nkt->k',s_hat_abs,s_hat_abs)
    
    frequency_order=np.argsort(spectral_similarity)
    
    #音源間の相関が最も低い周波数からパーミュテーションを解く
    is_first=True
    permutations=list(itertools.permutations(range(n_sources)))
    permutation_index_result={}
    
    for freq in frequency_order:
        
        if is_first==True:
            is_first=False

            #初期値を設定する
            accumurate_s_abs=s_hat_abs[:,frequency_order[0],:]
            permutation_index_result[freq]=range(n_sources)
        else:
            max_correlation=0
            max_correlation_perm=None
            for perm in permutations:
                s_hat_abs_temp=s_hat_abs[list(perm),freq,:]
                correlation=np.sum(accumurate_s_abs*s_hat_abs_temp)
                
                
                if max_correlation_perm is None:
                    max_correlation_perm=list(perm)
                    max_correlation=correlation
                elif max_correlation < correlation:
                    max_correlation=correlation
                    max_correlation_perm=list(perm)
            permutation_index_result[freq]=max_correlation_perm
            accumurate_s_abs+=s_hat_abs[max_correlation_perm,freq,:]
   
    return(permutation_index_result)
    
#プロジェクションバックで最終的な出力信号を求める
#s_hat: M,Nk,Lt
#W: 分離フィルタ(Nk,M,M)
#retunr c_hat: マイクロホン位置での分離結果(M,M,Nk,Lt)
def projection_back(s_hat,W):
    
    #ステアリングベクトルを推定
    A=np.linalg.pinv(W)
    c_hat=np.einsum('kmi,ikt->mikt',A,s_hat)
    return(c_hat)


#2バイトに変換してファイルに保存
#signal: time-domain 1d array (float)
#file_name: 出力先のファイル名
#sample_rate: サンプリングレート
def write_file_from_time_signal(signal,file_name,sample_rate):
    #2バイトのデータに変換
    signal=signal.astype(np.int16)

    #waveファイルに書き込む
    wave_out = wave.open(file_name, 'w')

    #モノラル:1、ステレオ:2
    wave_out.setnchannels(1)

    #サンプルサイズ2byte
    wave_out.setsampwidth(2)

    #サンプリング周波数
    wave_out.setframerate(sample_rate)

    #データを書き込み
    wave_out.writeframes(signal)

    #ファイルを閉じる
    wave_out.close()

#SNRをはかる
#desired: 目的音、Lt
#out:　雑音除去後の信号 Lt
def calculate_snr(desired,out):
    wave_length=np.minimum(np.shape(desired)[0],np.shape(out)[0])

    #消し残った雑音
    desired=desired[:wave_length]
    out=out[:wave_length]
    noise=desired-out
    snr=10.*np.log10(np.sum(np.square(desired))/np.sum(np.square(noise)))

    return(snr)

#乱数の種を初期化
np.random.seed(0)

#畳み込みに用いる音声波形
clean_wave_files=["./CMU_ARCTIC/cmu_us_aew_arctic/wav/arctic_a0001.wav","./CMU_ARCTIC/cmu_us_axb_arctic/wav/arctic_a0002.wav"]

#音源数
n_sources=len(clean_wave_files)

#長さを調べる
n_samples=0
#ファイルを読み込む
for clean_wave_file in clean_wave_files:
    wav=wave.open(clean_wave_file)
    if n_samples<wav.getnframes():
        n_samples=wav.getnframes()
    wav.close()

clean_data=np.zeros([n_sources,n_samples])

#ファイルを読み込む
s=0
for clean_wave_file in clean_wave_files:
    wav=wave.open(clean_wave_file)
    data=wav.readframes(wav.getnframes())
    data=np.frombuffer(data, dtype=np.int16)
    data=data/np.iinfo(np.int16).max
    clean_data[s,:wav.getnframes()]=data
    wav.close()
    s=s+1


# シミュレーションのパラメータ

#シミュレーションで用いる音源数
n_sim_sources=2

#サンプリング周波数
sample_rate=16000

#フレームサイズ
N=1024

#フレームシフト
Nshift=int(N/4)

#周波数の数
Nk=int(N/2+1)

#各ビンの周波数
freqs=np.arange(0,Nk,1)*sample_rate/N

#音声と雑音との比率 [dB]
SNR=90.

#方位角の閾値
azimuth_th=30.

#部屋の大きさ
room_dim = np.r_[10.0, 10.0, 10.0]

#マイクロホンアレイを置く部屋の場所
mic_array_loc = room_dim / 2 + np.random.randn(3) * 0.1 

#マイクロホンアレイのマイク配置
mic_directions=np.array(
    [[np.pi/2., theta/180.*np.pi] for theta in np.arange(180,361,180)
    ]    )

distance=0.01
mic_alignments=np.zeros((3, mic_directions.shape[0]), dtype=mic_directions.dtype)
mic_alignments[0, :] = np.cos(mic_directions[:, 1]) * np.sin(mic_directions[:, 0])
mic_alignments[1, :] = np.sin(mic_directions[:, 1]) * np.sin(mic_directions[:, 0])
mic_alignments[2, :] = np.cos(mic_directions[:, 0])
mic_alignments *= distance

#マイクロホン数
n_channels=np.shape(mic_alignments)[1]

#get the microphone array
R=mic_alignments+mic_array_loc[:,None]

is_use_reverb=True

if is_use_reverb==False:
    # 部屋を生成する
    room = pa.ShoeBox(room_dim, fs=sample_rate, max_order=0) 
    room_no_noise_left = pa.ShoeBox(room_dim, fs=sample_rate, max_order=0)
    room_no_noise_right = pa.ShoeBox(room_dim, fs=sample_rate, max_order=0)

else:

    room = pa.ShoeBox(room_dim, fs=sample_rate, max_order=17,absorption=0.4)
    room_no_noise_left = pa.ShoeBox(room_dim, fs=sample_rate, max_order=0)
    room_no_noise_right = pa.ShoeBox(room_dim, fs=sample_rate, max_order=0)

# 用いるマイクロホンアレイの情報を設定する
room.add_microphone_array(pa.MicrophoneArray(R, fs=room.fs))
room_no_noise_left.add_microphone_array(pa.MicrophoneArray(R, fs=room.fs))
room_no_noise_right.add_microphone_array(pa.MicrophoneArray(R, fs=room.fs))

#音源の場所
doas=np.array(
    [[np.pi/2., np.pi],
     [np.pi/2., 0]
    ]    )

#音源とマイクロホンの距離
distance=1.

source_locations=np.zeros((3, doas.shape[0]), dtype=doas.dtype)
source_locations[0, :] = np.cos(doas[:, 1]) * np.sin(doas[:, 0])
source_locations[1, :] = np.sin(doas[:, 1]) * np.sin(doas[:, 0])
source_locations[2, :] = np.cos(doas[:, 0])
source_locations *= distance
source_locations += mic_array_loc[:, None]

#各音源をシミュレーションに追加する
for s in range(n_sim_sources):
    clean_data[s]/= np.std(clean_data[s])
    room.add_source(source_locations[:, s], signal=clean_data[s])
    if s==0:
        room_no_noise_left.add_source(source_locations[:, s], signal=clean_data[s])
    if s==1:
        room_no_noise_right.add_source(source_locations[:, s], signal=clean_data[s])

#シミュレーションを回す
room.simulate(snr=SNR)
room_no_noise_left.simulate(snr=90)
room_no_noise_right.simulate(snr=90)

#畳み込んだ波形を取得する(チャンネル、サンプル）
multi_conv_data=room.mic_array.signals
multi_conv_data_left_no_noise=room_no_noise_left.mic_array.signals
multi_conv_data_right_no_noise=room_no_noise_right.mic_array.signals

#畳み込んだ波形をファイルに書き込む
write_file_from_time_signal(multi_conv_data_left_no_noise[0,:]*np.iinfo(np.int16).max/20.,"./lgm_dereverb_left_clean.wav",sample_rate)

#畳み込んだ波形をファイルに書き込む
write_file_from_time_signal(multi_conv_data_right_no_noise[0,:]*np.iinfo(np.int16).max/20.,"./lgm_dereverb_right_clean.wav",sample_rate)

#畳み込んだ波形をファイルに書き込む
write_file_from_time_signal(multi_conv_data[0,:]*np.iinfo(np.int16).max/20.,"./lgm_dereverb_in_left.wav",sample_rate)
write_file_from_time_signal(multi_conv_data[0,:]*np.iinfo(np.int16).max/20.,"./lgm_dereverb_in_right.wav",sample_rate)

#短時間フーリエ変換を行う
f,t,stft_data=sp.stft(multi_conv_data,fs=sample_rate,window="hann",nperseg=N,noverlap=N-Nshift)

#ICAの繰り返し回数
n_ica_iterations=50

#残響除去のパラメータ
D=2
Lh=5

#過去のマイクロホン入力信号
x_bar=make_x_bar(stft_data,D,Lh)

#ILRMAの基底数
n_basis=2

#処理するフレーm数
Lt=np.shape(stft_data)[-1]

#ICAの分離フィルタを初期化
Wilrma=np.zeros(shape=(Nk,n_sources,n_sources),dtype=np.complex)
Pilrma_t=np.zeros(shape=(Nk,n_sources,(Lh+1)*n_sources),dtype=np.complex)
#Wica=np.random.normal(size=Nk*n_sources*n_sources)+1.j*np.random.normal(size=Nk*n_sources*n_sources)
#Wica=np.reshape(Wica,(Nk,n_sources,n_sources))

Wilrma=Wilrma+np.eye(n_sources)[None,...]

Wilrma_ip=Wilrma.copy()

for tau in range(0,Lh+1):
    Pilrma_t[:,:,tau*n_sources:(tau+1)*n_sources]=Wilrma.copy()

#ILRMA用
b=np.ones(shape=(Nk,n_sources,n_basis))
a=np.random.uniform(size=(n_basis*n_sources*Lt))
a=np.reshape(a,(n_basis,n_sources,Lt))

start_time=time.time()

#ILRMA-Tに基づく音源分離と残響除去
Wilrma_t,s_ilrma_t,cost_buff_ilrma_t=execute_ip_time_varying_gaussian_ilrma_t(stft_data,x_bar,Pilrma_t,a.copy(),b.copy(),n_iterations=n_ica_iterations)

y_ilrma_t=projection_back(s_ilrma_t,Wilrma_t)

#IP法に基づくIVA実行コード（引数に与える関数を変更するだけ)
Wilrma_dereverb_ip,s_ilrma_dereverb_ip,cost_buff_ilrma_dereverb_ip=execute_ip_time_varying_gaussian_ilrma_dereverb(stft_data,x_bar,Wilrma_ip.copy(),a.copy(),b.copy(),n_iterations=n_ica_iterations)

#Wilrma_ip,s_ilrma_ip,cost_buff_ilrma_ip=execute_ip_time_varying_gaussian_ilrma(stft_data,Wilrma_ip,a,b,n_iterations=n_ica_iterations)

y_ilrma_dereverb_ip=projection_back(s_ilrma_dereverb_ip,Wilrma_dereverb_ip)

#IP法に基づくIVA実行コード（引数に与える関数を変更するだけ)
Wilrma_ip,s_ilrma_ip,cost_buff_ilrma_ip=execute_ip_time_varying_gaussian_ilrma(stft_data,Wilrma_ip,a.copy(),b.copy(),n_iterations=n_ica_iterations)

#Wilrma_ip,s_ilrma_ip,cost_buff_ilrma_ip=execute_ip_time_varying_gaussian_ilrma(stft_data,Wilrma_ip,a,b,n_iterations=n_ica_iterations)

y_ilrma_ip=projection_back(s_ilrma_ip,Wilrma_ip)
ilrma_ip_time=time.time()

#MM法に基づくLGM実行コード
Rlgm_mm_dereverb,vlgm_mm_dereverb,y_lgm_mm_dereverb,cost_buff_lgm_mm_dereverb=execute_mm_lgm_dereverb(stft_data,x_bar,Ns=n_sources,n_iterations=n_ica_iterations)
permutation_index_result=solver_inter_frequency_permutation(y_lgm_mm_dereverb[0,...])
#パーミュテーションを解く
for k in range(Nk):
    y_lgm_mm_dereverb[:,:,k,:]=y_lgm_mm_dereverb[:,permutation_index_result[k],k,:]

lgm_mm_time=time.time()


Rlgm_mm,vlgm_mm,y_lgm_mm,cost_buff_lgm_mm=execute_mm_lgm(stft_data,Ns=n_sources,n_iterations=n_ica_iterations)
permutation_index_result=solver_inter_frequency_permutation(y_lgm_mm[0,...])
for k in range(Nk):
    y_lgm_mm[:,:,k,:]=y_lgm_mm[:,permutation_index_result[k],k,:]

lgm_mm_time=time.time()

t,y_ilrma_ip=sp.istft(y_ilrma_ip[0,...],fs=sample_rate,window="hann",nperseg=N,noverlap=N-Nshift)
t,y_ilrma_t=sp.istft(y_ilrma_t[0,...],fs=sample_rate,window="hann",nperseg=N,noverlap=N-Nshift)
t,y_ilrma_dereverb_ip=sp.istft(y_ilrma_dereverb_ip[0,...],fs=sample_rate,window="hann",nperseg=N,noverlap=N-Nshift)
t,y_lgm_mm=sp.istft(y_lgm_mm[0,...],fs=sample_rate,window="hann",nperseg=N,noverlap=N-Nshift)
t,y_lgm_mm_dereverb=sp.istft(y_lgm_mm_dereverb[0,...],fs=sample_rate,window="hann",nperseg=N,noverlap=N-Nshift)

snr_pre=calculate_snr(multi_conv_data_left_no_noise[0,...],multi_conv_data[0,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],multi_conv_data[0,...])
snr_pre/=2.

snr_ilrma_t_post1=calculate_snr(multi_conv_data_left_no_noise[0,...],y_ilrma_t[0,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],y_ilrma_t[1,...])
snr_ilrma_t_post2=calculate_snr(multi_conv_data_left_no_noise[0,...],y_ilrma_t[1,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],y_ilrma_t[0,...])

snr_ilrma_t_post=np.maximum(snr_ilrma_t_post1,snr_ilrma_t_post2)
snr_ilrma_t_post/=2.

snr_ilrma_ip_post1=calculate_snr(multi_conv_data_left_no_noise[0,...],y_ilrma_ip[0,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],y_ilrma_ip[1,...])
snr_ilrma_ip_post2=calculate_snr(multi_conv_data_left_no_noise[0,...],y_ilrma_ip[1,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],y_ilrma_ip[0,...])

snr_ilrma_ip_post=np.maximum(snr_ilrma_ip_post1,snr_ilrma_ip_post2)
snr_ilrma_ip_post/=2.

snr_ilrma_dereverb_ip_post1=calculate_snr(multi_conv_data_left_no_noise[0,...],y_ilrma_dereverb_ip[0,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],y_ilrma_dereverb_ip[1,...])
snr_ilrma_dereverb_ip_post2=calculate_snr(multi_conv_data_left_no_noise[0,...],y_ilrma_dereverb_ip[1,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],y_ilrma_dereverb_ip[0,...])

snr_ilrma_dereverb_ip_post=np.maximum(snr_ilrma_dereverb_ip_post1,snr_ilrma_dereverb_ip_post2)
snr_ilrma_dereverb_ip_post/=2.

snr_lgm_mm_post1=calculate_snr(multi_conv_data_left_no_noise[0,...],y_lgm_mm[0,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],y_lgm_mm[1,...])
snr_lgm_mm_post2=calculate_snr(multi_conv_data_left_no_noise[0,...],y_lgm_mm[1,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],y_lgm_mm[0,...])

snr_lgm_mm_post=np.maximum(snr_lgm_mm_post1,snr_lgm_mm_post2)
snr_lgm_mm_post/=2.


snr_lgm_mm_dereverb_post1=calculate_snr(multi_conv_data_left_no_noise[0,...],y_lgm_mm_dereverb[0,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],y_lgm_mm_dereverb[1,...])
snr_lgm_mm_dereverb_post2=calculate_snr(multi_conv_data_left_no_noise[0,...],y_lgm_mm_dereverb[1,...])+calculate_snr(multi_conv_data_right_no_noise[0,...],y_lgm_mm_dereverb[0,...])

snr_lgm_mm_dereverb_post=np.maximum(snr_lgm_mm_dereverb_post1,snr_lgm_mm_dereverb_post2)
snr_lgm_mm_dereverb_post/=2.


write_file_from_time_signal(y_ilrma_ip[0,...]*np.iinfo(np.int16).max/20.,"./ilrma_ip_1.wav",sample_rate)
write_file_from_time_signal(y_ilrma_ip[1,...]*np.iinfo(np.int16).max/20.,"./ilrma_ip_2.wav",sample_rate)

write_file_from_time_signal(y_ilrma_dereverb_ip[0,...]*np.iinfo(np.int16).max/20.,"./ilrma_dereverb_ip_1.wav",sample_rate)
write_file_from_time_signal(y_ilrma_dereverb_ip[1,...]*np.iinfo(np.int16).max/20.,"./ilrma_dereverb_ip_2.wav",sample_rate)

write_file_from_time_signal(y_ilrma_t[0,...]*np.iinfo(np.int16).max/20.,"./ilrma_t_1.wav",sample_rate)
write_file_from_time_signal(y_ilrma_t[1,...]*np.iinfo(np.int16).max/20.,"./ilrma_t_2.wav",sample_rate)

write_file_from_time_signal(y_lgm_mm[0,...]*np.iinfo(np.int16).max/20.,"./lgm_mm_1.wav",sample_rate)
write_file_from_time_signal(y_lgm_mm[1,...]*np.iinfo(np.int16).max/20.,"./lgm_mm_2.wav",sample_rate)

write_file_from_time_signal(y_lgm_mm_dereverb[0,...]*np.iinfo(np.int16).max/20.,"./lgm_mm_dereverb_1.wav",sample_rate)
write_file_from_time_signal(y_lgm_mm_dereverb[1,...]*np.iinfo(np.int16).max/20.,"./lgm_mm_dereverb_2.wav",sample_rate)


print("method:    ", "ILRMA", "ILRMA-Dereverb","ILRMA-T","LGM-MM","LGM-Dereverb-MM")
#print("処理時間[sec]: {:.2f} [sec] {:.2f} [sec]".format(ilrma_ip_time-start_time,lgm_mm_time-start_time))
print("Δsnr [dB]:  {:.2f}  {:.2f}  {:.2f}  {:.2f}  {:.2f}".format(snr_ilrma_ip_post-snr_pre,snr_ilrma_dereverb_ip_post-snr_pre,snr_ilrma_t_post-snr_pre,snr_lgm_mm_post-snr_pre,snr_lgm_mm_dereverb_post-snr_pre))

#コストの値を表示
#for t in range(n_ica_iterations):
#    print(t,cost_buff_ica[t],cost_buff_iva[t],cost_buff_iva_ip[t],cost_buff_ilrma_ip[t],cost_buff_lgm_em[t],cost_buff_lgm_mm[t])

